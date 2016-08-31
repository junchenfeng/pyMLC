import numpy as np
from collections import defaultdict
from tqdm import tqdm



import ipdb

def survivial_llk(h,E):
	# h, T*1 hazard rate
	# T, spell length
	# E, whether right censored
	T = len(h)
	if T == 1:
		base_prob = 1
	else:
		# has survived T-1 period
		base_prob = np.product(1-h[:-1])

	prob = base_prob*(E*h[-1]+(1-E)*(1-h[-1]))
	return prob

def state_llk(X,init_dist,transit_matrix):
	# X: vector of latent state, list
	# transit matrix is np array [t-1,t]
	prob = init_dist[X[0]] * np.product([transit_matrix[X[t-1],X[t]] for t in range(1,len(X))])

	return prob
	
def likelihood(X, O, E, harzard_matrix, observ_matrix, state_init_dist, state_transit_matrix):
	# X:  Latent state
	# O: observation
	# E: binary indicate whether the spell is ended
	T = len(X)
	# P(E|O,X)
	h = np.array([harzard_matrix[O[t]] for t in range(T)])
	pa = survivial_llk(h,E)
	
	# P(O|X)
	po = np.product([observ_matrix[X[t],O[t]] for t in range(T)])

	# P(X)
	px = state_llk(X, state_init_dist, state_transit_matrix)
	
	return pa*po*px
	
def generate_possible_states(T):
	# because of the left-right constraints, the possible state is T+1
	X_mat = np.ones([T+1,T])
	for t in range(1,T+1):
		X_mat[t,:t]=0
	return X_mat

def get_llk_all_states(X_mat,O,E,harzard_matrix, observ_matrix, state_init_dist,state_transit_matrix):
	N_X = X_mat.shape[0]
	llk_vec = []
	
	for i in range(N_X):
		X = [int(x) for x in X_mat[i,:].tolist()]
		llk_vec.append( likelihood(X, O, E, harzard_matrix, observ_matrix, state_init_dist,state_transit_matrix) )
		
	return np.array(llk_vec)

def get_single_state_llk(X_mat, llk_vec, t, x):
	res = llk_vec[X_mat[:,t]==x].sum() 
	return res

def get_joint_state_llk(X_mat,llk_vec,t,x1,x2):
	if t==0:
		raise ValueException('t must > 0.')
	res = llk_vec[ (X_mat[:,t-1]==x1) & (X_mat[:,t]==x2) ].sum() 
	return res

def get_E(E,t,T):
	if E == 0:
		Et = 0
	else:
		if t ==T:
			Et = 1
		else:
			Et = 0
	return Et
	
class BKT_HMM_SURVIVAL(object):
	def __init__(self, init_param):
		self.g = init_param['g']  # guess
		self.s = init_param['s']  # slippage
		self.pi = init_param['pi']  # initial prob of mastery
		self.l = init_param['l']  # learn speed
		self.h0 = init_param['h0']  # harzard rate with response 0
		self.h1 = init_param['h1']  # harzard rate with response 1

			
	def _load_observ(self, data):
		# the input data are [(i,t,y,e)] because learner practice length is not necessary the same
		# TODO: assume T starts from 0
		self.K = len(set([x[0] for x in data]))
		self.T = max([x[1] for x in data]) + 1
		
		self.E_array = np.empty((self.T, self.K))
		self.O_array = np.empty((self.T, self.K))
		T_array = np.zeros((self.K,))
		
		for log in data:
			i = log[0]; t = log[1]; y = log[2]; is_e = log[3]
			self.O_array[t, i] = y
			self.E_array[t, i] = is_e
			T_array[i] = t
		
		self.T_vec = [int(x)+1 for x in T_array.tolist()] 
		self.O_data = []
		for i in range(self.K):
			self.O_data.append( [int(x) for x in self.O_array[0:self.T_vec[i],i].tolist()] )
		self.E_vec = [int(self.E_array[self.T_vec[i]-1, i]) for i in range(self.K)]		
				
		# initialize
		self._update_derivative_parameter()  # learning spead
		self._collapse_obser_state()

	def __update_pi(self, t, h, E, observ, pi_vec, P_mat):
		# pi(i,t) = P(X_t=i|O1,...,O_t,\theta)
		if t == 0:
			pa = survivial_llk(h, E)			
			# pi(i,0) = P(X_0=i|O0,\theta)
			p0y = (1-self.pi)*self.observ_matrix[0,observ]*pa
			p1y = self.pi*self.observ_matrix[1,observ]*pa
			py = p0y+p1y
			pi_vec[t,0] = p0y/py
			pi_vec[t,1] = p1y/py
		else:
			# pi(i,t) = sum_{j} P(j,i,t) where P(j,i,t) is the (j,i)the element of transition matrix P
			pi_vec[t,:] = P_mat[t-1,:,:].sum(axis=0)
		
		return pi_vec
			
	def __update_P(self, t, h, E, observ, pi_vec, P_mat):
		p_raw = np.zeros((2,2))
		pa = survivial_llk(h, E)
		p_raw[0,0] = pi_vec[t,0]*self.state_transit_matrix[0,0]*self.observ_matrix[0,observ]*pa
		p_raw[0,1] = pi_vec[t,0]*self.state_transit_matrix[0,1]*self.observ_matrix[1,observ]*pa
		p_raw[1,0] = pi_vec[t,1]*self.state_transit_matrix[1,0]*self.observ_matrix[0,observ]*pa
		p_raw[1,1] = pi_vec[t,1]*self.state_transit_matrix[1,1]*self.observ_matrix[1,observ]*pa
		
		P_mat[t,:,:] = p_raw/p_raw.sum()
		return P_mat		
		
	def _update_derivative_parameter(self):
		self.state_init_dist = np.array([1-self.pi, self.pi])
		self.state_transit_matrix = np.array([[1-self.l, self.l], [0, 1]])
		self.observ_matrix = np.array([[1-self.g, self.g], [self.s, 1-self.s]])  # index by state, observ
		self.harzard_matrix = np.array([self.h0, self.h1])
	
	def _collapse_obser_state(self):
		self.obs_type_cnt = defaultdict(int)
		self.obs_type_ref = {}
		for k in range(self.K):
			obs_type_key = str(self.E_vec[k]) + '-' + '|'.join(str(y) for y in self.O_data[k])
			self.obs_type_cnt[obs_type_key] += 1
			self.obs_type_ref[k] = obs_type_key
		# construct the space
		self.obs_type_info = {}
		for key in self.obs_type_cnt.keys():
			e_s, O_s = key.split('-')
			self.obs_type_info[key] = {'E':int(e_s),'O':[int(x) for x in O_s.split('|')]}		
			
	def _MCMC(self, max_iter, method='FB'):
		self.parameter_chain = np.empty((max_iter, 6))
		# initialize for iteration
		for iter in tqdm(range(max_iter)):
			# Step 1: Data Augmentation
			
			if method == "DG":
			
				# calculate the sample prob
				for key in self.obs_type_info.keys():
					# get the obseration state
					O = self.obs_type_info[key]['O']
					E = self.obs_type_info[key]['E']
					
					#calculate the exhaustive state probablity
					Ti = len(O)					
					X_mat = generate_possible_states(Ti)
					llk_vec = get_llk_all_states(X_mat, O, E, self.harzard_matrix, self.observ_matrix, self.state_init_dist, self.state_transit_matrix)
					
					
					self.obs_type_info[key]['pi'] = get_single_state_llk(X_mat, llk_vec, 0, 1)/llk_vec.sum()
					self.obs_type_info[key]['l_vec'] = [ get_joint_state_llk(X_mat, llk_vec, t, 0, 1) /get_single_state_llk(X_mat, llk_vec, t-1, 0) for t in range(1,Ti)]
					
				# sample states
				X = np.empty((self.T, self.K))
				for i in range(self.K):
					# check the key
					obs_key = self.obs_type_ref[i]
					pi = self.obs_type_info[obs_key]['pi']
					l_vec = self.obs_type_info[obs_key]['l_vec']
					
					X[0,i] = np.random.binomial(1,pi)
					for t in range(1, self.T_vec[i]):
						if X[t-1,i] == 1:
							X[t,i] = 1
						else:
							X[t,i] = np.random.binomial(1,l_vec[t-1])
							
			elif method == "FB":
				# calculate the sample prob
				for key in self.obs_type_info.keys():
					# get the obseration state			
					Os = self.obs_type_info[key]['O']
					E = self.obs_type_info[key]['E']
					#calculate the exhaustive state probablity
					T = len(Os)
					pi_vec = np.zeros((T,2))
					P_mat = np.zeros((T-1,2,2))
					
					for t in range(T):
						h = np.array([self.harzard_matrix[Os[m]] for m in range(t+1)])
						Et = get_E(E,t,T)
						pi_vec = self.__update_pi(t, h, Et, Os[t], pi_vec, P_mat)
						if t !=T-1:
							h = np.array([self.harzard_matrix[Os[m]] for m in range(t+2)])
							Et = get_E(E,t+1,T)
							P_mat = self.__update_P(t, h, Et, Os[t+1], pi_vec, P_mat)
					
					self.obs_type_info[key]['pi'] = pi_vec
					self.obs_type_info[key]['P'] = P_mat

				# calculate the probability
				#self.obs_type_info[key]['llk'] = self._get_llk(self.s, self.g, self.pi, self.l, [Os])
								
				# backward sampling
				X = np.empty((self.T, self.K))
				init_pis = np.zeros((self.K, 1))
				for k in range(self.K):
					# check for the observation type
					obs_key = self.obs_type_ref[k]
					pi_vec = self.obs_type_info[obs_key]['pi']
					P_mat = self.obs_type_info[obs_key]['P']
					for t in range(self.T_vec[k]-1,-1,-1):
						if t == self.T_vec[k]-1:
							p = pi_vec[t,1]
						else:
							next_state = int(X[t+1,k])
							p = P_mat[t,1,next_state]/P_mat[t,:,next_state].sum()
						if t == 0:
							init_pis[k] = p
						X[t,k] = np.random.binomial(1,p)
				# 
						
			# Step 2: Update Parameter
			critical_trans = 0
			tot_trans = 0
			obs_cnt = np.zeros((2,2)) # state,observ
			drop_cnt = np.zeros((2,)) # state,observ
			survive_cnt = np.zeros((2,))
			
			for k in range(self.K):
				for t in range(0, self.T_vec[k]):
					# update l
					if t>0 and X[t-1,k] == 0:
						tot_trans += 1
						if X[t,k] == 1:
							critical_trans += 1
					# update obs_cnt
					obs_cnt[int(X[t,k]),int(self.O_array[t,k])] += 1

			for t in range(1,self.T):
				# for data survived in last period, check the harzard rate
				for k in range(self.K):
					if self.T_vec[k]>=t and  self.E_array[t-1,k] == 0:
						drop_cnt[int(self.O_array[t,k])] += self.E_array[t,k]
						survive_cnt[int(self.O_array[t,k])] += 1-self.E_array[t,k]
			
			
			self.l = np.random.beta(1+critical_trans, 4+tot_trans-critical_trans)
			self.pi = np.random.beta(2+sum(X[0,:]),2+self.K-sum(X[0,:]))
			self.s = np.random.beta(1+obs_cnt[1,0],9+obs_cnt[1,1])
			self.g = np.random.beta(1+obs_cnt[0,1],3+obs_cnt[0,0])


			self.h0 = np.random.beta(1+drop_cnt[0], 9 + survive_cnt[0])
			self.h1 = np.random.beta(1+drop_cnt[1], 9 + survive_cnt[1])
			
			self.parameter_chain[iter, :] = [self.s, self.g, self.pi, self.l, self.h0, self.h1]
			self._update_derivative_parameter()
			# for monitoring purpose
			if iter%100 == 0:
				print(iter)	
			
	def estimate(self, data_array, max_iter=1000):
	
		self._load_observ(data_array)
	
		self._MCMC(max_iter)
		
		def get_point_estimation(data_array):
			# keep the 10%-90%
			lower = np.percentile(data_array, 0.1)
			valid_data = data_array[data_array>lower]
			# take mean
			est = valid_data.mean()
			return est
		
		self.s = 	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),0])
		self.g = 	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),1])
		self.pi =	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),2])
		self.l = 	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),3])
		self.h0 = 	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),4])
		self.h1 = 	get_point_estimation(self.parameter_chain[range(int(max_iter/2),max_iter,20),5])
	
		
if __name__=='__main__':
	'''
	# UNIT TEST
	# parameter
	s = 0.05
	g = 0.2
	pi = 0.4
	l = 0.3
	

	h00 = 0.3
	h01 = 0.2
	h10 = 0.1
	h11 = 0.05

	X = [0,1,1] 
	O = [1,0,1]
	E = 0
	
	# true prob
	#px = 0.7*0.2*1
	#po = 0.2*0.05*0.95
	#pa = (1-0.3)*(1-0.2)*(1-0.1)
	prob = likelihood(X,O,E,harzard_matrix, observ_matrix, state_init_dist,state_transit_matrix) # 0.00067032
	print([prob,0.00067032])
	
	E = 1
	#pa = (1-0.3)*(1-0.2)*0.1
	prob = likelihood(X,O,E,harzard_matrix, observ_matrix, state_init_dist,state_transit_matrix) # 0.00007448
	print([prob,0.00007448])
	
	E = 0
	X = [1,1,1]
	# px = 0.3*1*1
	# po = 0.95*0.05*0.95
	# pa = 0.9*0.8*0.9
	prob = likelihood(X,O,E,harzard_matrix, observ_matrix, state_init_dist,state_transit_matrix) # 0.0087723
	print([prob,0.0087723])
	'''
	
	
	
	
	#UNIT TEST II: In limiting case where h is always equal 0 and the spell never ends, we should recover the resetimation
	'''
	data_array = [(0,0,0,0),(0,1,1,0)]
	init_param = {'s':0.1,
			  'g':0.2, 
			  'pi':0.5,
			  'l':0.1,
			  'h00':0.0,
			  'h01':0.0,
			  'h10':0.0,
			  'h11':0.0}
	x1 = BKT_HMM_SURVIVAL(init_param)
	x1.estimate(data_array, max_iter=1)
	
	get_single_state_llk(X_mat,llk_vec,0,0)/llk_vec.sum() # 0.7058
	get_single_state_llk(X_mat,llk_vec,0,1)/llk_vec.sum() # 0.2942
	get_single_state_llk(X_mat,llk_vec,1,0)/llk_vec.sum() # 0.4706
	get_single_state_llk(X_mat,llk_vec,1,1)/llk_vec.sum() # 0.5294
	
	get_joint_state_llk(X_mat,llk_vec,1,0,0)/llk_vec.sum() # 0.4706
	get_joint_state_llk(X_mat,llk_vec,1,0,1)/llk_vec.sum() # 0.2353
	get_joint_state_llk(X_mat,llk_vec,1,1,0)/llk_vec.sum() # 0
	get_joint_state_llk(X_mat,llk_vec,1,1,1)/llk_vec.sum() # 0.2941
	'''
	
	'''
	init_param = {'s':s,
				  'g':g, 
				  'pi':pi,
				  'l':l,
				  'h00':h00,
				  'h01':h01,
				  'h10':h10,
				  'h11':h11}
	'''
	
	'''
	init_param = {'s':np.random.uniform(0,0.2),
				  'g':np.random.uniform(0,0.4), 
				  'pi':np.random.uniform(0,1),
				  'l':np.random.uniform(0,1),
				  'h00':np.random.uniform(0,1),
				  'h01':np.random.uniform(0,1),
				  'h10':np.random.uniform(0,1),
				  'h11':np.random.uniform(0,1)
	}	
	'''
	
	
	

	import os			  
	max_obs = 250
	
	proj_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))	
	data_array = []
	data_cnt = 0
	with open(proj_dir+'/data/BKT/test/single_sim.txt') as f:
		for line in f:
			i_s, t_s, y_s, x_s, is_e_s, is_a_s = line.strip().split(',')
			
			if int(i_s) == max_obs:
				break
			
			if int(is_a_s):
				data_array.append( (int(i_s), int(t_s), int(y_s), int(is_e_s)) )	
			data_cnt += 1	

	y0s = [log[2] for log in data_array if log[1]==0]
	y1s = [log[2] for log in data_array if log[1]==1]
	yTs = [log[2] for log in data_array if log[1]==4]
	
	EYs = [(log[2], log[3]) for log in data_array if log[1]>0]
	h1 = float(  sum([x[1] for x in EYs if x[0]==1]) )/len([x[0] for x in EYs if x[0]==1])
	h0 = float(  sum([x[1] for x in EYs if x[0]==0]) )/len([x[0] for x in EYs if x[0]==0])
	
	init_param = {'s': 1-np.array(yTs).mean(),
				  'g': 0.3, 
				  'pi': np.array(y0s).mean(),
				  'l': np.array(y1s).mean() - np.array(y0s).mean(),
				  'h0': h0,
				  'h1': h1}
				  
	init_param = {'s':np.random.uniform(0,0.5),
				  'g':np.random.uniform(0,0.5), 
				  'pi':np.random.uniform(0,1),
				  'l':np.random.uniform(0,1),
				  'h0':np.random.uniform(0,1),
				  'h1':np.random.uniform(0,1)}	

	x1 = BKT_HMM_SURVIVAL(init_param)
	x1.estimate(data_array, max_iter=1000)
	print(init_param['s'],init_param['g'],init_param['pi'],init_param['l'], init_param['h0'],init_param['h1'])
	print(x1.s, x1.g, x1.pi, x1.l, x1.h0, x1.h1)
	ipdb.set_trace()	

	def update_mastery(mastery, learn_rate):
		return mastery + (1-mastery)*learn_rate

	def compute_success_rate(guess, slip, mastery):
		return guess*(1-mastery) + (1-slip)*mastery		
		
	def generate_learning_curve(slip, guess, init_mastery, learn_rate, T):
		p=init_mastery
		lc = [compute_success_rate(guess, slip, p)]
		for t in range(1,T):
			p = update_mastery(p,learn_rate)
			lc.append(compute_success_rate(guess, slip, p))
		return lc

	true_lc = generate_learning_curve(0.05, 0.2, 0.4, 0.3, 5)
	est_lc = generate_learning_curve(x1.s, x1.g, x1.pi, x1.l, 5)
	
	

	
	print(true_lc)
	print(est_lc)	
	
	ipdb.set_trace()
			
