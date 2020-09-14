import re
import sys
import glob
import datetime as dt
import imageio
import numpy as np
import pandas as pd
import networkx as nx
today = dt.datetime.now()
runname = sys.argv[1]

import matplotlib.pyplot as plt
from matplotlib import colors
import warnings
warnings.filterwarnings('ignore')

nodesize = 150
fnodesize = 200
solcol = 'goldenrod'
batcol = 'lightseagreen'
nodecol = 'grey'
fnodecol = 'crimson'
branchcol = 'darkcyan'
fbranchcol = 'snow'
branchwidth = 7

netfiles = glob.glob("netimgs/t_*.csv")
tsteps = sorted(list(set([int(re.search(r'\d+',f).group()) for f in netfiles])))

def plot_net(t,G,fnodes,solar,batt,stat,i,j):
    plt.figure(figsize=(10,7))
    pos=nx.kamada_kawai_layout(G)
    nx.draw_networkx_nodes(G,pos,
                           nodelist=G.nodes,
                           node_color=nodecol,
                           node_size=nodesize,
                           with_labels=False)
    nx.draw_networkx_nodes(G,pos,
                           nodelist=solar,
                           node_color=solcol,
                           node_size=nodesize,
                           with_labels=['SOLAR']*len(solar))
    plt.scatter([],[],s=nodesize,color=solcol,label='node with solar')
    nx.draw_networkx_nodes(G,pos,
                           nodelist=batt,
                           node_color=batcol,
                           node_size=nodesize,
                           with_labels=['BATTERY']*len(batt))
    plt.scatter([],[],s=nodesize,color=batcol,label='node with battery')
    if len(fnodes)>0:
        nx.draw_networkx_nodes(G,pos,
                               nodelist=fnodes,
                               node_color=fnodecol,
                               node_size=fnodesize,
                               with_labels=True)
    nx.draw_networkx_edges(G,pos,
                           edgelist=G.edges,
                           edge_color=branchcol,
                           width=branchwidth)
    openswitches = [e for e in G.edges if not G.edges[e][stat]]
    if len(openswitches)>0:
        nx.draw_networkx_edges(G,pos,
                               edgelist=openswitches,
                               edge_color=fbranchcol,
                               width=branchwidth)
    desc = {0:'',1:'fault isolation',2:'islanded state'}
    plt.legend(loc='upper left',ncol=2,frameon=False)
    plt.text(0.2,-0.95,'t={:03d} : {}'.format(t,desc[j]),fontsize=20)
    plt.axis('off')
    plt.savefig('netimgs/network-{}-{}.png'.format(i,j),bbox_inches='tight',transparent=False,dpi=400)
    plt.clf()

for i,t in enumerate(tsteps):
    branch_df = pd.read_csv("netimgs/t_{}-branchdf.csv".format(t))
    fnodes = pd.read_csv("netimgs/t_{}-faultednodes.csv".format(t),header=None,index_col=0)
    fnodes = list(fnodes[1])
    solar = pd.read_csv("netimgs/t_{}-solar.csv".format(t),header=None,index_col=0)
    solar = list(solar[1])
    batt = pd.read_csv("netimgs/t_{}-batt.csv".format(t),header=None,index_col=0)
    batt = list(batt[1])
    edges = [(branch_df.loc[i,'t'], branch_df.loc[i,'f'], {'status00':branch_df.loc[i,'st00'], 'status0':branch_df.loc[i,'st0'], 'status1':branch_df.loc[i,'st1']}) for i in branch_df.index]
    G = nx.Graph()
    G.add_edges_from(edges)
    if i==0:
        plot_net(t,G,[],solar,batt,'status00',i,0) #net status at node fault
    plot_net(t,G,fnodes,solar,batt,'status0',i,1)  #net status after node isolation
    plot_net(t,G,fnodes,solar,batt,'status1',i,2)  #net status after virtual islanding

namesuff = '-{}'*len(fnodes)
namesuff = namesuff.format(*fnodes)

images = []
imgfiles = sorted(glob.glob("netimgs/*.png"))
for filename in imgfiles:
    images.append(imageio.imread(filename))
imageio.mimsave('netimgs/netsim-{}'.format(runname)+namesuff+'.gif', images, duration=0.8)
