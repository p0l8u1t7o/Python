import torch
import torch.nn as nn
from torchvision.models import resnet50, ResNet50_Weights

class PatchCoreModel(nn.Module):
    def __init__(self):
        super().__init__()

        backbone = resnet50(weights=ResNet50_Weights.DEFAULT)

        # 取 layer2 & layer3
        self.layer1 = nn.Sequential(*list(backbone.children())[:5])
        self.layer2 = list(backbone.children())[5]
        self.layer3 = list(backbone.children())[6]

    def forward(self, x):
        x = self.layer1(x)

        f2 = self.layer2(x)   # (512, H/8)
        f3 = self.layer3(f2)  # (1024, H/16)

        return f2, f3