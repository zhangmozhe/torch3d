import torch
import torch.nn as nn
import torch3d.nn.functional as F


__all__ = [
    "XConv",
    "SetAbstraction"
]


class XConv(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, dilation=1, bias=True):
        super(XConv, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.mid_channels = out_channels // 4
        self.kernel_size = kernel_size
        self.dilation = dilation
        self.bias = bias
        self.mlp = nn.Sequential(
            nn.Conv2d(3, self.mid_channels, 1, bias=self.bias),
            nn.BatchNorm2d(self.mid_channels),
            nn.ReLU(True),
            nn.Conv2d(self.mid_channels, self.mid_channels, 1, bias=self.bias),
            nn.BatchNorm2d(self.mid_channels),
            nn.ReLU(True),
        )
        self.stn = nn.Sequential(
            nn.Conv2d(3, self.kernel_size ** 2, [1, self.kernel_size], bias=self.bias),
            nn.BatchNorm2d(self.kernel_size ** 2),
            nn.ReLU(True),
            nn.Conv2d(self.kernel_size ** 2, self.kernel_size ** 2, 1, bias=self.bias),
            nn.BatchNorm2d(self.kernel_size ** 2),
            nn.ReLU(True),
            nn.Conv2d(self.kernel_size ** 2, self.kernel_size ** 2, 1, bias=self.bias),
        )
        self.conv = nn.Sequential(
            nn.Conv2d(self.in_channels + self.mid_channels,
                      self.out_channels,
                      [1, self.kernel_size],
                      bias=self.bias),
            nn.BatchNorm2d(self.out_channels),
            nn.ReLU(True),
        )

    def forward(self, p, q, x=None):
        batch_size = p.shape[0]
        _, indices = F.knn(p, q, self.kernel_size * self.dilation)
        indices = indices[..., ::self.dilation]
        p = torch.stack([p[b, i] for b, i in enumerate(indices)], dim=0)
        p_hat = p - q.unsqueeze(2)
        p_hat = p_hat.permute(0, 3, 1, 2)
        x_hat = self.mlp(p_hat)
        x_hat = x_hat.permute(0, 2, 3, 1)
        if x is not None:
            x = x.permute(0, 2, 1)
            x = torch.stack([x[b, i] for b, i in enumerate(indices)], dim=0)
            x_hat = torch.cat([x_hat, x], dim=-1)
        T = self.stn(p_hat)
        T = T.view(batch_size, self.kernel_size, self.kernel_size, -1)
        T = T.permute(0, 3, 1, 2)
        x_hat = torch.matmul(T, x_hat)
        x = x_hat
        x = x.permute(0, 3, 1, 2)
        x = self.conv(x)
        x = x.squeeze(3)
        return q, x


class SetAbstraction(nn.Module):
    def __init__(self, mlp, radius=None, k=None, bias=True):
        super(SetAbstraction, self).__init__()
        self.radius = radius
        self.k = k
        self.bias = bias
        modules = []
        last_channels = mlp[0]
        for channels in mlp[1:]:
            modules.append(nn.Conv2d(last_channels, channels, 1, bias=self.bias))
            modules.append(nn.BatchNorm2d(channels))
            modules.append(nn.ReLU(True))
            last_channels = channels
        self.mlp = nn.Sequential(*modules)
        self.maxpool = nn.MaxPool2d([1, k])

    def forward(self, p, q, x=None):
        if self.radius is not None:
            indices = F.ball_point(p, q, self.radius, self.k)
            p = torch.stack([p[b, i] for b, i in enumerate(indices)], dim=0)
            p_hat = p - q.unsqueeze(2)
            x_hat = p_hat
        else:
            x_hat = p.unsqueeze(1)
        if x is not None:
            x = x.permute(0, 2, 1)
            if self.radius is not None:
                x = torch.stack([x[b, i] for b, i in enumerate(indices)], dim=0)
            else:
                x = x.unsqueeze(1)
            x_hat = torch.cat([x_hat, x], dim=-1)
        x = x_hat.permute(0, 3, 1, 2)
        x = self.mlp(x)
        x = self.maxpool(x).squeeze(3)
        return q, x
