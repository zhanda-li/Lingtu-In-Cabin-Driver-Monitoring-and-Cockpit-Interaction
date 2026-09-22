"""轻量时序 Transformer：窗口内骨骼序列 -> 4 分类。

结构：线性投影 -> 拼 CLS token -> 加位置编码 -> TransformerEncoder -> CLS 头

为什么用 CLS token 而不是平均池化：
    平均池化把窗口内所有帧等同看待，而"疲劳点头"的关键信息在局部
    （某几次点头的波峰）。CLS token 让模型自己学会该关注哪几帧。

规模 16.2 万参数（窗口 45 时实测 161,988），CPU 单次前向 < 5 ms，现场实时绰绰有余。
"""

import torch
import torch.nn as nn


class PoseTransformer(nn.Module):
    def __init__(self, feat_dim, window, n_class,
                 d_model=64, n_head=4, n_layer=3, dropout=0.1):
        super().__init__()
        self.feat_dim = feat_dim
        self.window = window
        self.n_class = n_class

        self.proj = nn.Linear(feat_dim, d_model)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_model))
        self.pos_embed = nn.Parameter(torch.zeros(1, window + 1, d_model))
        self.drop = nn.Dropout(dropout)

        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=n_head,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,        # pre-LN：小模型 + 小数据集上比 post-LN 稳得多
        )
        self.encoder = nn.TransformerEncoder(
            layer, num_layers=n_layer, norm=nn.LayerNorm(d_model))
        self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, n_class))

        nn.init.trunc_normal_(self.cls_token, std=0.02)
        nn.init.trunc_normal_(self.pos_embed, std=0.02)
        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(m):
        if isinstance(m, nn.Linear):
            nn.init.trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)

    def forward(self, x):
        """x: (B, window, feat_dim) -> logits (B, n_class)"""
        h = self.proj(x)                                    # (B, W, D)
        cls = self.cls_token.expand(h.size(0), -1, -1)
        h = torch.cat([cls, h], dim=1) + self.pos_embed      # (B, W+1, D)
        h = self.encoder(self.drop(h))
        return self.head(h[:, 0])                           # 取 CLS 位置的输出

    def n_params(self):
        return sum(p.numel() for p in self.parameters())
