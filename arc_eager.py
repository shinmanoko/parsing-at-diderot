import io
from collections import defaultdict
from SparseWeightVector import SparseWeightVector
from random import randrange
from math import inf


#DATA REPRESENTATION
class DependencyTree:

    def __init__(self,tokens=None, edges=None):
        self.edges  = [] if edges is None else edges                      #couples (gov_idx,dep_idx)
        self.tokens = [('$ROOT$','$ROOT$')] if tokens is None else tokens #couples (wordform,postag)
    
    def __str__(self):
        gdict = dict([(d,g) for (g,d) in self.edges])
        return '\n'.join(['\t'.join([str(idx+1),tok[0],tok[1],str(gdict[idx+1])]) for idx,tok in enumerate(self.tokens[1:])])
                     
    def __make_ngrams(self):
        """
        Makes word representations suitable for feature extraction
        """
        BOL = '@@@'
        EOL = '$$$'
        wordlist = [BOL] + list([w for w,t in self.tokens]) + [EOL]
        taglist = [BOL] + list([t for w,t in self.tokens]) + [EOL]
        word_trigrams = list(zip(wordlist,wordlist[1:],wordlist[2:]))
        tag_trigrams  = list(zip(taglist,taglist[1:],taglist[2:]))
        self.tokens   = list(zip(wordlist[1:-1],taglist[1:-1],word_trigrams,tag_trigrams))
        
    @staticmethod
    def read_tree(istream):
        """
        Reads a tree from an input stream
        @param istream: the stream where to read from
        @return: a DependencyTree instance 
        """
        deptree = DependencyTree()
        bfr = istream.readline()
        while True:
            if (bfr.isspace() or bfr == ''):
                if deptree.N() > 1:
                    deptree.__make_ngrams()
                    return deptree
                bfr = istream.readline()
            else:
                idx, word, tag, governor_idx = bfr.split()
                deptree.tokens.append((word,tag))
                deptree.edges.append((int(governor_idx),int(idx)))
                bfr = istream.readline()
        deptree.__make_ngrams()
        return deptree

    def accurracy(self,other):
        """
        Compares this dep tree with another by computing their UAS.
        @param other: other dep tree
        @return : the UAS as a float
        """
        assert(len(self.edges) == len(other.edges))
        S1 = set(self.edges)
        S2 = set(other.edges)
        return len(S1.intersection(S2)) / len(S1)
    
    def N(self):
        """
        Returns the length of the input
        """
        return len(self.tokens)
    
    def __getitem__(self,idx):
        """
        Returns the token at index idx
        """
        return self.tokens[idx]

class ArcEagerTransitionParser:

    #actions
    LEFTARC  = "LA"
    RIGHTARC = "RA"
    SHIFT    = "S"
    REDUCE   = "R"
    TERMINATE= "T"
    
    def __init__(self):
        self.model = SparseWeightVector()
        
    @staticmethod
    def static_oracle(configuration,reference_arcs,N):
        """
        @param configuration: a parser configuration
        @param reference arcs: a set of dependency arcs
        @param N: the length of the input sequence
        @return the action to execute given config and reference arcs
        """
        S,B,A,score = configuration
        all_words   = range(N)
        
        if S and B:
            i,j = S[-1], B[0]
            if i!= 0 and (j,i) in reference_arcs:
                return ArcEagerTransitionParser.LEFTARC
            if  (i,j) in reference_arcs:
                return ArcEagerTransitionParser.RIGHTARC
        if S and any([(k,S[-1]) in A for k in all_words])\
            and all ([(S[-1],k) in A for k in all_words if (S[-1],k) in reference_arcs]):
            return ArcEagerTransitionParser.REDUCE
        if B:
            return ArcEagerTransitionParser.SHIFT
        return ArcEagerTransitionParser.TERMINATE

    @staticmethod
    def dynamic_oracle(configuration,action,reference_arcs):
        """
        Computes the cost of an action given a configuration and a reference tree
        @param configuration: a parser configuration tuple
        @param reference_arcs a set of dependencies
        @return a bool set to true if cost = 0 , false otherwise (cost > 0 or impossible action)
        """
        S,B,A,score = configuration
        if S and B:
            i,j = S[-1],B[0]
            if action == ArcEagerTransitionParser.LEFTARC:
                if any ([(k,i) in reference_arcs for k in B[1:]]):
                    return False
                if any([(i,k) in reference_arcs for k in B]):
                    return False
                return True
            elif action == ArcEagerTransitionParser.RIGHTARC:
                if any([(k,j) in reference_arcs for k in B]):
                    return False
                if any([(k,j) in reference_arcs for k in S[:-1]]):
                    return False
                if any([(j,k) in reference_arcs for k in S]):
                    return False
                return True
        if S:
            if action == ArcEagerTransitionParser.REDUCE:
                if any([(i,k) in reference_arcs for k in B]):
                    return False
                return True

        if B:
            if action == ArcEagerTransitionParser.SHIFT:
                if any([(j,k) in reference_arcs or (k,j) in reference_arcs for k in S]):
                    return False
                return True
        if not B and action == ArcEagerTransitionParser.TERMINATE:
            return True
        
        return False

            
    def static_oracle_derivation(self,ref_parse):
        """
        This generates a static oracle reference derivation from a sentence
        @param ref_parse: a DependencyTree object
        @return : the oracle derivation as a list of (Configuration,action,toklist) triples
        """
        sentence = ref_parse.tokens
        edges    = set(ref_parse.edges)
        N        = len(sentence)
        
        C = ((0,),tuple(range(1,len(sentence))),tuple(),0.0)       #A config is a hashable quadruple with score 
        action = ArcEagerTransitionParser.static_oracle(C,edges,N)
        derivation = [ (C,action,sentence) ]

        while C[1] and action != ArcEagerTransitionParser.TERMINATE:
            #print(C,action)
            if action ==  ArcEagerTransitionParser.SHIFT:
                C = self.shift(C,sentence)
            elif action == ArcEagerTransitionParser.LEFTARC:
                C = self.leftarc(C,sentence)
            elif action == ArcEagerTransitionParser.RIGHTARC:
                C = self.rightarc(C,sentence)
            elif action == ArcEagerTransitionParser.REDUCE:
                C = self.reduce_config(C,sentence)
            elif action ==  ArcEagerTransitionParser.TERMINATE:
                C = self.terminate(C,sentence)

            action = ArcEagerTransitionParser.static_oracle(C,edges,N)
            derivation.append((C,action,sentence))
                            
        return derivation
                
    def shift(self,configuration,tokens):
        """
        Performs the shift action and returns a new configuration
        """
        S,B,A,score = configuration
        w0 = B[0]
        return (S + (w0,),B[1:],A,score+self.score(configuration,ArcEagerTransitionParser.SHIFT,tokens)) 

    def leftarc(self,configuration,tokens):
        """
        Performs the left arc action and returns a new configuration
        """
        S,B,A,score = configuration
        i,j = S[-1],B[0]
        return (S[:-1],B,A + ((j,i),),score+self.score(configuration,ArcEagerTransitionParser.LEFTARC,tokens)) 

    def rightarc(self,configuration,tokens):
        S,B,A,score = configuration
        i,j = S[-1],B[0]
        return (S+(j,),B[1:], A + ((i,j),),score+self.score(configuration,ArcEagerTransitionParser.RIGHTARC,tokens)) 

    def reduce_config(self,configuration,tokens):
        S,B,A,score = configuration
        return (S[:-1],B,A,score+self.score(configuration,ArcEagerTransitionParser.REDUCE,tokens))
    
    def terminate(self,configuration,tokens):
        S,B,A,score = configuration
        return (S,B,A,score+self.score(configuration,ArcEagerTransitionParser.TERMINATE,tokens))        

    def predict_local(self,configuration,sentence,allowed=None):
        """
        Statistical prediction of an action given a configuration
        @param configuration: a tuple (S,B,A,score)
        @param sentence: a list of tokens
        @param allowed:  a list of allowed actions
        @return (new_config,action_performed)
        """
        action_set = set([ArcEagerTransitionParser.LEFTARC,ArcEagerTransitionParser.RIGHTARC,\
                          ArcEagerTransitionParser.SHIFT,ArcEagerTransitionParser.REDUCE,\
                          ArcEagerTransitionParser.TERMINATE])
        if allowed :
            action_set = set(allowed)
        
        N = len(sentence)
        S,B,A,score = configuration
        candidates = []
        if B and ArcEagerTransitionParser.SHIFT in action_set :
            candidates.append((self.shift(configuration,sentence),ArcEagerTransitionParser.SHIFT))
            
        if S and ArcEagerTransitionParser.REDUCE in action_set:
            i = S[-1]    
            if any([(k,i) in A for k in range(N)]):
                candidates.append((self.reduce_config(configuration,sentence),ArcEagerTransitionParser.REDUCE))

        if S and B:
            if ArcEagerTransitionParser.LEFTARC in action_set:
                i = S[-1]     
                if i != 0 and not any([(k,i) in A for k in range(N)]): 
                    candidates.append((self.leftarc(configuration,sentence),ArcEagerTransitionParser.LEFTARC))
            if ArcEagerTransitionParser.RIGHTARC in action_set:
                j = B[0]
                if not any([(k,j) in A for k in range(N)]):
                    candidates.append((self.rightarc(configuration,sentence),ArcEagerTransitionParser.RIGHTARC))

        if not B and ArcEagerTransitionParser.TERMINATE in action_set:
            candidates.append((self.terminate(configuration,sentence),ArcEagerTransitionParser.TERMINATE))

        if candidates:
            candidates.sort(key=lambda x:x[0][3],reverse=True)
            return candidates[0]    
        else: #emergency exit when we have no candidate
            return (C,ArcEagerTransitionParser.TERMINATE)

    def parse_one(self,sentence):
        """
        Greedy parsing
        @param sentence: a list of tokens
        """
        N = len(sentence)
        C = ((0,),tuple(range(1,N)),tuple(),0.0) #A config is a hashable quadruple with score 
        action = None
        while action != ArcEagerTransitionParser.TERMINATE:
            C,action = self.predict_local(C,sentence)

        #Connects any remaining dummy root to 0 
        S,B,A,score = C
        Aset = set(A)
        for s in S:
            if s!= 0 and not any([(k,s) in Aset for k in range(N)]):
                Aset.add((0,s))
        return DependencyTree(tokens=sentence,edges=list(Aset))


    def score(self,configuration,action,tokens):
        """
        Computes the prefix score of a derivation
        @param configuration : a quintuple (S,B,A,score,history)
        @param action: an action label in {LEFTARC,RIGHTARC,REDUCE,TERMINATE,SHIFT}
        @param tokens: the x-sequence of tokens to be parsed
        @return a prefix score
        """
        S,B,A,old_score = configuration
        config_repr = self.__make_config_representation(S,B,tokens)
        return old_score + self.model.dot(config_repr,action)

    def __make_config_representation(self,S,B,tokens):
        """
        This gathers the information for coding the configuration as a feature vector.
        @param S: a configuration stack
        @param B  a configuration buffer
        @return an ordered list of tuples 
        """
        #default values for inaccessible positions
        s0w,s1w,s0t,s1t,b0w,b1w,b0t,b1t = "_UNDEF_","_UNDEF_","_UNDEF_","_UNDEF_","_UNDEF_","_UNDEF_","_UNDEF_","_UNDEF_"

        if len(S) > 0:
            s0w,s0t = tokens[S[-1]][0],tokens[S[-1]][1]
        if len(S) > 1:
            s1w,s1t = tokens[S[-2]][0],tokens[S[-2]][1]
        if len(B) > 0:
            b0w,b0t = tokens[B[0]][0],tokens[B[0]][1]
        if len(B) > 1:
            b1w,b1t = tokens[B[1]][0],tokens[B[1]][1]
            
        wordlist = [s0w,s1w,b0w,b1w]
        taglist  = [s0t,s1t,b0t,b1t]
        word_bigrams = list(zip(wordlist,wordlist[1:]))
        tag_bigrams = list(zip(taglist,taglist[1:]))
        word_trigrams = list(zip(wordlist,wordlist[1:],wordlist[2:]))
        tag_trigrams = list(zip(taglist,taglist[1:],taglist[2:]))
        return word_bigrams + tag_bigrams + word_trigrams + tag_trigrams
    
    def test(self,dataset):
        """
        @param dataset: a list of DependencyTrees
        @param beam_size: size of the beam
        """
        N       = len(dataset)
        sum_acc = 0.0
        for ref_tree in dataset:
            tokens    = ref_tree.tokens
            pred_tree = self.parse_one(tokens)
            print(pred_tree)
            print()
            sum_acc   += ref_tree.accurracy(pred_tree)
        return sum_acc/N

    
    def choose(self,pred_action,optimal_actions):
        """
        Choice function for dynamic oracle. Chooses next action in case of ambiguity.
        (does not perform exploration) 
        """
        if pred_action in optimal_actions:
            return pred_action
        else:
            return optimal_actions[randrange(0,len(optimal_actions))]
        
    def dynamic_train(self,treebank,step_size=1.0,max_epochs=100):

        ACTIONS = [ArcEagerTransitionParser.LEFTARC,ArcEagerTransitionParser.RIGHTARC,\
                   ArcEagerTransitionParser.SHIFT,ArcEagerTransitionParser.REDUCE,\
                   ArcEagerTransitionParser.TERMINATE]
        
        N = len(treebank)
        for e in range(max_epochs):
            loss, total = 0,0
            for dtree in treebank:
                ref_arcs = set(dtree.edges)
                n = len(dtree.tokens)
                C = ((0,),tuple(range(1,n)),tuple(),0.0) #A config is a hashable quadruple with score 
                action = None
                while action != ArcEagerTransitionParser.TERMINATE:
                    pred_config,pred_action = self.predict_local(C,dtree.tokens)
                    optimal_actions = list([a for a in ACTIONS if self.dynamic_oracle(C,a,ref_arcs)])
                    total += 1
                    if pred_action not in optimal_actions:
                        loss +=1
                        optimal_config,optimal_action = self.predict_local(C,dtree.tokens,allowed=optimal_actions)
                        delta_ref = SparseWeightVector()
                        S,B,A,score = C
                        x_repr = self.__make_config_representation(S,B,dtree.tokens)
                        delta_ref += SparseWeightVector.code_phi(x_repr,optimal_action)

                        delta_pred = SparseWeightVector()
                        S,B,A,score = C
                        x_repr = self.__make_config_representation(S,B,dtree.tokens)
                        delta_pred += SparseWeightVector.code_phi(x_repr,pred_action)

                        self.model += step_size*(delta_ref-delta_pred)
                        
                    action = self.choose(pred_action,optimal_actions)
                
                    if action ==  ArcEagerTransitionParser.SHIFT:
                        C = self.shift(C,dtree.tokens)
                    elif action == ArcEagerTransitionParser.LEFTARC:
                        C = self.leftarc(C,dtree.tokens)
                    elif action == ArcEagerTransitionParser.RIGHTARC:
                        C = self.rightarc(C,dtree.tokens)
                    elif action == ArcEagerTransitionParser.REDUCE:
                        C = self.reduce_config(C,dtree.tokens)
                    elif action ==  ArcEagerTransitionParser.TERMINATE:
                        C = self.terminate(C,dtree.tokens)
            print('Loss = ',loss, "%Local accurracy = ",(total-loss)/total)
            if loss == 0.0:
                return
                            
    def static_train(self,treebank,step_size=1.0,max_epochs=100):
        """
        Trains a model with a static oracle
        @param treebank : a list of dependency trees
        """
        dataset = []
        for dtree in treebank:
            dataset.extend(self.static_oracle_derivation(dtree))
        N = len(dataset)
        for e in range(max_epochs):
            loss = 0.0
            for ref_config,ref_action,tokens in dataset:
                pred_config,pred_action = self.predict_local(ref_config,tokens)
                if ref_action != pred_action:
                    loss += 1.0
                    delta_ref = SparseWeightVector()
                    S,B,A,score = ref_config
                    x_repr = self.__make_config_representation(S,B,tokens)
                    delta_ref += SparseWeightVector.code_phi(x_repr,ref_action)
                                
                    delta_pred = SparseWeightVector()
                    S,B,A,score = ref_config
                    x_repr = self.__make_config_representation(S,B,tokens)
                    delta_pred += SparseWeightVector.code_phi(x_repr,pred_action)

                    self.model += step_size*(delta_ref-delta_pred)
            print('Loss = ',loss, "%Local accurracy = ",(N-loss)/N)
            if loss == 0.0:
                return

            
test = """
1 le   D     2
2 chat N     3
3 dort V     0
4 .    PONCT 3
"""
test2 = """
1 le      D     2
2 tapis   N     3
3 est     V     5
4 rouge   A     3
5 et      CC    0
6 le      D     7
7 chat    N     8
8 mange   V     5
9 la      D     10
10 souris N     8
11 .      PONCT 5
"""

istream = io.StringIO(test)
istream2 =  io.StringIO(test2)
d = DependencyTree.read_tree(istream)
d2 = DependencyTree.read_tree(istream2)
p = ArcEagerTransitionParser()
#p.static_train([d,d2],max_epochs=10)
#print(p.test([d,d2]))
p.dynamic_train([d,d2],max_epochs=10)
print(p.test([d,d2]))
