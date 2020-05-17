import os
import random
from functools import partialmethod

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch.nn import Linear

from torch_geometric.nn import (ARMAConv, ChebConv, FeaStConv, GATConv,
                                GCNConv, GINConv, GraphConv, TAGConv,
                                JumpingKnowledge, RGCNConv, SAGEConv, SGConv,
                                SplineConv)

from .pyg_utils import generate_pyg_data


def partialclass(cls, *args, **kwargs):
    class NewCls(cls):
        __init__ = partialmethod(cls.__init__, *args, **kwargs)
    NewCls.__name__ = f'{cls.__name__}[{kwargs}]'
    return NewCls


SEARCH_SPACE = {
    'conv_class': [
        # GCNConv,
        # partialclass(GCNConv, improved=True),
        partialclass(GCNConv, normalize=True),

        # partialclass(ChebConv, K=3),
        partialclass(ChebConv, K=7),

        # partialclass(TAGConv, K=3),
        partialclass(TAGConv, K=5),

        partialclass(SGConv, K=2),
        partialclass(ARMAConv, num_layers=3, num_stacks=2),
        partialclass(GraphConv, aggr='mean'),

        partialclass(SAGEConv),
        # partialclass(SAGEConv, normalize=True),
    ],
    'hidden_size': [32, 64],
    'num_layers': [1],
    'in_dropout': [0.5],
    'out_dropout': [0.5],
    'n_iter': [100, 300],
    'weight_decay': [1e-3],
    'learning_rate': [0.01, 0.001],
}


def fix_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True


WITH_EDGE_WEIGHTS = ['ChebConv', 'GCNConv', 'SAGEConv', 'GraphConv', 'TAGConv', 'ARMAConv']


def with_edge_weights(conv_mod):
    for c in WITH_EDGE_WEIGHTS:
        if f'.{c}' in str(type(conv_mod)):
            return True
    return False


class GCN(torch.nn.Module):

    def __init__(self, *, conv_class, num_layers, hidden, features_num=32, num_class=2, in_dropout=0, out_dropout=0):
        super().__init__()
        self.convs = torch.nn.ModuleList()
        for i in range(num_layers):
            self.convs.append(conv_class(hidden, hidden))

        self.in_nn = Linear(features_num, hidden)
        self.out_nn = Linear(hidden, num_class)

        self.in_drop = torch.nn.Dropout(in_dropout)
        self.out_drop = torch.nn.Dropout(out_dropout)

    def reset_parameters(self):
        self.in_nn.reset_parameters()
        self.conv1.reset_parameters()
        for conv in self.convs:
            conv.reset_parameters()
        self.lin2.reset_parameters()

    def forward(self, data):
        x, edge_index, edge_weight = data.x, data.edge_index, data.edge_weight

        x = F.relu(self.in_nn(x))
        x = self.in_drop(x)

        for conv in self.convs:
            if with_edge_weights(conv):
                x = conv(x, edge_index, edge_weight=edge_weight)
            else:
                x = conv(x, edge_index)

            x = F.relu(x)

        x = self.out_drop(x)
        x = self.out_nn(x)

        return x

    def __repr__(self):
        return self.__class__.__name__


class Restorable:
    def save(self, path):
        torch.save(self.model.state_dict(), os.path.join(path, 'model.pt'))
        torch.save(self.optimizer.state_dict(), os.path.join(path, 'optimizer.pt'))

    def restore(self, path):
        self.model.load_state_dict(torch.load(os.path.join(path, 'model.pt')))
        self.optimizer.load_state_dict(torch.load(os.path.join(path, 'optimizer.pt')))


class PYGModel(Restorable):

    def __init__(self, n_classes, input_size, conv_class, hidden_size, num_layers, in_dropout, out_dropout,
                 n_iter, weight_decay, learning_rate):
        self.conv_class = conv_class
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.device = torch.device('cuda')
        self.n_iter = n_iter

        self.model = GCN(
            features_num=input_size, num_class=n_classes,
            num_layers=self.num_layers, conv_class=self.conv_class, hidden=self.hidden_size,
            in_dropout=in_dropout, out_dropout=out_dropout,
        )
        self.model = self.model.to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate, weight_decay=weight_decay)

    def train(self, data, full=False):
        data = data.to(self.device)

        self.model.train()
        for epoch in range(1, self.n_iter):
            self.optimizer.zero_grad()
            if full:
                mask = data.train_mask + data.val_mask
            else:
                mask = data.train_mask

            loss = F.cross_entropy(self.model(data)[mask], data.y[mask])
            loss.backward()
            self.optimizer.step()

        with torch.no_grad():
            self.model.eval()
            y_pred_val = self.model(data)[data.val_mask].cpu().numpy().argmax(axis=1)

        y_val_true = data.y[data.val_mask].cpu().numpy()
        val_acc = (y_pred_val == y_val_true).mean()
        return val_acc

    def predict(self, data):
        self.model.eval()
        data = data.to(self.device)
        with torch.no_grad():
            pred = self.model(data)[data.test_mask]
        return pred.cpu().numpy()

    def fit_predict(self, data, full=False):
        score = self.train(data, full=full)
        pred = self.predict(data)
        return pred, score


def create_factory_method(n_classes, input_size):

    def create_model(**config):
        return PYGModel(
            n_classes, input_size=input_size,
            conv_class=config['conv_class'], hidden_size=config['hidden_size'],
            num_layers=config['num_layers'], in_dropout=config['in_dropout'], out_dropout=config['out_dropout'],
            n_iter=config['n_iter'], weight_decay=config['weight_decay'], learning_rate=config['learning_rate']
            )

    return create_model
