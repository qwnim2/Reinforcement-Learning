import random
import math
import numpy as np
import torch
import torch.nn.functional as F
import torch.optim as optim
import torch.nn as nn
from collections import namedtuple
from agent_dir.agent import Agent
from environment import Environment


use_cuda = torch.cuda.is_available()
device = torch.device("cuda" if use_cuda else "cpu")

class DQN(nn.Module):
    '''
    This architecture is the one from OpenAI Baseline, with small modification.
    '''
    def __init__(self, channels, num_actions):
        super(DQN, self).__init__()
        self.conv1 = nn.Conv2d(channels, 32, kernel_size=8, stride=4)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=4, stride=2)
        self.conv3 = nn.Conv2d(64, 64, kernel_size=3, stride=1)
        self.fc = nn.Linear(3136, 512)
        self.head = nn.Linear(512, num_actions)

        self.relu = nn.ReLU()
        self.lrelu = nn.LeakyReLU(0.01)


    def forward(self, x):
        x = self.relu(self.conv1(x))
        x = self.relu(self.conv2(x))
        x = self.relu(self.conv3(x))
        x = self.lrelu(self.fc(x.view(x.size(0), -1)))
        q = self.head(x)
        return q

# Dueling-dqn class
# class DUELING_DQN(nn.Module):
#     '''
#     This architecture is the one from OpenAI Baseline, with small modification.
#     '''
#     def __init__(self, channels, num_actions):
#         super(DUELING_DQN, self).__init__()
#         self.conv1 = nn.Conv2d(channels, 32, kernel_size=8, stride=4)
#         self.conv2 = nn.Conv2d(32, 64, kernel_size=4, stride=2)
#         self.conv3 = nn.Conv2d(64, 64, kernel_size=3, stride=1)

#         self.fc_adv = nn.Linear(3136, 512)
#         self.fc_val = nn.Linear(3136, 512)

#         self.head_adv = nn.Linear(512, num_actions)
#         self.head_val = nn.Linear(512, 1)
#         self.relu = nn.ReLU()
#         self.lrelu = nn.LeakyReLU(0.01)


#     def forward(self, x):
#         x = self.relu(self.conv1(x))
#         x = self.relu(self.conv2(x))
#         x = self.relu(self.conv3(x))
#         x = x.view(x.size(0), -1)

#         adv = self.lrelu(self.fc_adv(x))
#         val = self.lrelu(self.fc_val(x))

#         adv = self.head_adv(adv)
#         val = self.head_val(val).expand(x.size(0), 9)
#         #q = self.head(x)
#         q = val + adv - adv.mean(1).unsqueeze(1).expand(x.size(0), 9)
#         return q

class AgentDQN(Agent):
    def __init__(self, env, args):#, num):
        self.env = env
        self.input_channels = 4
        self.num_actions = self.env.action_space.n      #num_actions = 9
        
        # self.num = num
        # build target, online network
        # if self.num == 1:
        #     self.target_net = DUELING_DQN(self.input_channels, self.num_actions)
        # elif self.num == 2:                                                       #for dueling-dqn
        self.target_net = DQN(self.input_channels, self.num_actions)
        self.target_net = self.target_net.cuda() if use_cuda else self.target_net

        # if self.num == 1:
        #     self.online_net = DUELING_DQN(self.input_channels, self.num_actions)  #for dueling-dqn
        # elif self.num == 2:
        self.online_net = DQN(self.input_channels, self.num_actions)
        self.online_net = self.online_net.cuda() if use_cuda else self.online_net

        if args.test_dqn:
            self.load('dqn')

        # discounted reward
        self.GAMMA = 0.99

        # training hyperparameters
        self.train_freq = 4 # frequency to train the online network
        self.learning_start = 10000 # before we start to update our network, we wait a few steps first to fill the replay.
        self.batch_size = 32
        self.num_timesteps = 500000#3000000 # total training steps
        self.display_freq = 10 # frequency to display training progress
        self.save_freq = 200000 # frequency to save the model
        self.target_update_freq = 1000 # frequency to update target network
        self.buffer_size = 10000 # max size of replay buffer

        # optimizer
        self.optimizer = optim.RMSprop(self.online_net.parameters(), lr=1e-4)

        self.steps = 0 # num. of passed steps

        # TODO: initialize your replay buffer
        self.replay = []
        self.position = 0
        
        #set the epsilon
        self.eps = 1.0  #init exploration rate
        self.eps_min = 0.1
        self.eps_decay = 0.995

    def save(self, save_path):
        print('save model to', save_path)
        torch.save(self.online_net.state_dict(), save_path + '_online.cpt')
        torch.save(self.target_net.state_dict(), save_path + '_target.cpt')

    def load(self, load_path):
        print('load model from', load_path)
        if use_cuda:
            self.online_net.load_state_dict(torch.load(load_path + '_online.cpt'))
            self.target_net.load_state_dict(torch.load(load_path + '_target.cpt'))
        else:
            self.online_net.load_state_dict(torch.load(load_path + '_online.cpt', map_location=lambda storage, loc: storage))
            self.target_net.load_state_dict(torch.load(load_path + '_target.cpt', map_location=lambda storage, loc: storage))

    def init_game_setting(self):
        # we don't need init_game_setting in DQN
        pass

    def make_action(self, state, test=False):
        # TODO:
        # Implement epsilon-greedy to decide whether you want to randomly select
        # an action or not.
        # HINT: You may need to use and self.steps
        if not test:
            sample = random.random()
            if sample > self.eps:
                with torch.no_grad():
                    action = self.online_net(state.cuda()).max(1)[1].item() #int
                    return action
            else:
                return random.randrange(self.num_actions)   #rand int 0~8

        with torch.no_grad():
            state = torch.from_numpy(state).permute(2,0,1).unsqueeze(0)
            action = self.online_net(state.cuda()).max(1)[1].item() #int
            return action

    def update(self):
        # TODO:
        # step 1: Sample some stored experiences as training examples.
        # step 2: Compute Q(s_t, a) with your model.
        # step 3: Compute Q(s_{t+1}, a) with target model.
        # step 4: Compute the expected Q values: rewards + gamma * max(Q(s_{t+1}, a))
        # step 5: Compute temporal difference loss
        # HINT:
        # 1. You should not backprop to the target model in step 3 (Use torch.no_grad)
        # 2. You should carefully deal with gamma * max(Q(s_{t+1}, a)) when it
        #    is the terminal state.
        Transition = namedtuple('Transition',
                        ('state', 'action', 'next_state', 'reward'))
        transitions = random.sample(self.replay, self.batch_size)
        mini_batch = Transition(*zip(*transitions))
        
        non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                          mini_batch.next_state)), device=device, dtype=torch.bool)
        non_final_next_states = torch.cat([s for s in mini_batch.next_state
                                                if s is not None])
        state_batch = torch.cat(mini_batch.state).cuda()
        action_batch = torch.cat((mini_batch.action)).cuda()
        reward_batch = torch.cat(mini_batch.reward).cuda()

        # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
        # columns of actions taken. These are the actions which would've been taken
        # for each batch state according to policy_net
        state_action_values = self.online_net(state_batch).gather(1, action_batch)

        # Compute V(s_{t+1}) for all next states.
        # Expected values of actions for non_final_next_states are computed based
        # on the "older" target_net; selecting their best reward with max(1)[0].
        # This is merged based on the mask, such that we'll have either the expected
        # state value or 0 in case the state was final.
        next_state_values = torch.zeros(self.batch_size, device=device)
        
        # Double-DQN
        # target_next_state_values = torch.zeros(self.batch_size, device=device)
        # online_next_state_values = torch.zeros(self.batch_size, device=device)
        # if num == 1:
        #     target_next_state_values = self.target_net(non_final_next_states.cuda())
        #     online_next_state_values = self.online_net(non_final_next_states.cuda())                                    ##for DDQN
        #     next_state_values[non_final_mask] = target_next_state_values.gather(1, 
        #                     online_next_state_values.max(1)[1].unsqueeze(1)).squeeze(1).detach()
        # elif num == 2:

        next_state_values[non_final_mask] = self.target_net(non_final_next_states.cuda()).max(1)[0].detach()

        # Compute the expected Q values
        expected_state_action_values = (next_state_values * self.GAMMA) + reward_batch

        # Compute mse loss
        loss = F.mse_loss(state_action_values.cuda(), expected_state_action_values.cuda().unsqueeze(1))

        # Optimize the model
        self.optimizer.zero_grad()
        loss.backward()
        for param in self.online_net.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()

        return loss.item()

    def train(self):
        from tensorboardX import SummaryWriter 
        writer = SummaryWriter(f'Dueling_DQN/reward{self.num}')

        episodes_done_num = 0 # passed episodes
        total_reward = 0 # compute average reward
        loss = 0
        while(True):
            state = self.env.reset()
            # State: (80,80,4) --> (1,4,80,80)
            state = torch.from_numpy(state).permute(2,0,1).unsqueeze(0)
            done = False
            while(not done):
                # select and perform action
                action = self.make_action(state)
                next_state, reward, done, _ = self.env.step(action)
                total_reward += reward

                # process new state
                next_state = torch.from_numpy(next_state).permute(2,0,1).unsqueeze(0)

                # TODO: store the transition in memory
                if len(self.replay) < self.buffer_size:
                    self.replay.append(None)
                action = torch.tensor(action, dtype=torch.long).view(1,1)
                reward = torch.tensor([reward], dtype = torch.long)
                self.replay[self.position] = (state, action, next_state, reward)
                self.position = (self.position + 1) % self.buffer_size
                
                # move to the next state
                state = next_state

                # Perform one step of the optimization
                if self.steps > self.learning_start and self.steps % self.train_freq == 0:
                    # if num == 1:
                    #     loss = self.update(1)
                    # elif num == 2:
                    #     loss = self.update(2)
                    loss = self.update()
                # TODO: update target network
                if self.steps > self.learning_start and self.steps % self.target_update_freq == 0:
                    self.target_net.load_state_dict(self.online_net.state_dict())

                # save the model
                if self.steps % self.save_freq == 0:
                    self.save('dqn')

                self.steps += 1
              
                if self.eps > self.eps_min:
                    self.eps *= self.eps_decay
             
            if episodes_done_num % self.display_freq == 0:
                print('Episode: %d | Steps: %d/%d | Avg reward: %f | loss: %f '%
                        (episodes_done_num, self.steps, self.num_timesteps, total_reward / self.display_freq, loss))
                if episodes_done_num % 100 == 0:
                    writer.add_scalar('Dueling-DQN', total_reward / self.display_freq, episodes_done_num)
                    writer.close()
                total_reward = 0

            episodes_done_num += 1
            if self.steps > self.num_timesteps:
                break
        self.save('dqn')
