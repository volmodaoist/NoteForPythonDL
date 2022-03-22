import tqdm
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader,TensorDataset


##采集多少张对抗样本用于展示

# How many adversarial samples to collect for display
SAMPLES = 7
FONT_DICT = dict(
    fontsize = 12,
    family = "Times New Roman",
    weight =  "light", 
    style = "italic",
)


epsilons = [0, 0.05, 0.1, 0.15, 0.20, 0.25 ,0.30]
pretrained_model = "../models/lenet_mnist_model.pth"

## 只要具有可用的GPU, 毫不犹豫的使用!
use_gpu = True
use_cuda = True if torch.cuda.is_available() else False
device = torch.device("cuda:0" if use_gpu and use_cuda else "cpu")


## 这是LeNet模型
class Net(nn.Module):
    def __init__(self) -> None:
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1,  10, kernel_size = 5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size = 5)
        self.conv2_drop = nn.Dropout2d()
        
        ## (N - F + 2P) / S
        ## 按照卷积核输出的公式来看, 为啥进入全连接层的特征只有320?
        self.fc1 = nn.Linear(320,50)
        self.fc2 = nn.Linear(50,10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x),2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training = self.training)
        x = self.fc2(x)
        return F.log_softmax(x, dim = 1)

test_loader = DataLoader(
    datasets.MNIST("../data"
        , train = False
        , download = True
        , transform = transforms.Compose([
            transforms.ToTensor()    
        ])
    ),
    batch_size = 1,
    shuffle = True
)


## 初始化网络并载入与训练的网络
model = Net().to(device)
model.load_state_dict(torch.load(pretrained_model, map_location = "cpu"))


## 网络分为训练模式与评估模式,
## 现将网络设为评估模式,这一条主要是针对丢弃层的设置,
model.eval()


## 获取梯度运算的符号函数, 将其乘以epsilon盖在原图身上
def pgd_attack(model, image, target, epsilon, alpha = 1/255, iters = 20):
    org_image = image.data
    for _ in tqdm.trange(iters):
        output = model(image)
        model.zero_grad()

        loss = F.cross_entropy(output, target)
        loss.backward()

        adv_image = image + alpha * image.grad.sign()
        eta = torch.clamp(adv_image - org_image, min = -epsilon, max = epsilon)
        perturbed_image = torch.clamp(org_image + eta, min = 0, max = 1)

    return perturbed_image




def test(model, device, test_laoder, epsilon):
    correct = 0
    adv_examples = []
    for data, target in test_loader:
        data, target = data.to(device), target.to(device)

        data.requires_grad = True

        output = model(data)

        ## Tensor调用max相当于一个面向对象写法的torch.max,
        ## Tensor调用max返回两批数组,分别是最大值及其所在位置的索引
        init_pred = output.max(1, keepdims=True)[1]

        ## 如果张量只有一个元素, 则可使用item将其转为标量
        ## 如果本来已经预测错误, ,则为自然误差, 可直接跳过当前样本
        if init_pred.item() != target.item():
            continue

        loss = F.nll_loss(output, target)

        ## 每次反向传播之前记得清零, 否则会累积梯度
        model.zero_grad()
        loss.backward()  
        perburted_data = pgd_attack(model, data, target, 0.5, epsilon)
        output = model(perburted_data)
        final_pred = output.max(1, keepdims=True)[1]
        if final_pred.item() == target.item():
            correct += 1
            if  epsilon == 0 and len(adv_examples) < SAMPLES:
                adv_ex = perburted_data.squeeze().detach().cpu().numpy()
                adv_examples.append((init_pred.item(), final_pred.item(), adv_ex))            
        else:
            if len(adv_examples) < SAMPLES:        
                adv_ex = perburted_data.squeeze().detach().cpu().numpy()
                adv_examples.append((init_pred.item(), final_pred.item(), adv_ex))
    final_acc = correct / float(len(test_laoder))
    print("Epsilon: {}\tTest accuracy = {}/{} = {}".format(epsilon, correct, len(test_loader), final_acc))
    return final_acc, adv_examples

    
if __name__ == "__main__":
    accuracies = []
    examples = []

    for eps in epsilons:
        acc, ex = test(model,device, test_loader, eps)
        accuracies.append(acc)
        examples.append(ex)
    
    with open("./records.txt", "a", encoding = "utf-8") as file:
        file.write("\n")
        file.write("PGD:")
        file.write("\n")
        file.write(str(accuracies))
        file.write("\n")

    plt.figure(figsize = (5, 5))
    plt.plot(epsilons, accuracies, "*-")
    plt.yticks(np.arange(0, 1.10, step = 0.10))
    plt.xticks(np.arange(0, 0.35, step = 0.05))
    plt.title("Accuracy vs Epsilon")
    plt.xlabel("Epsilon")
    plt.ylabel("Accuracy")
    plt.show()

    ## 绘制不同攻击强度的对抗样本采样
    cnt = 0
    plt.figure(figsize = (12, 16))
    plt.subplots_adjust(wspace = 0.1, hspace = 1.0)
    for i in range(len(epsilons)):
        for j in range(len(examples[i])):
            cnt += 1
            plt.subplot(len(epsilons),len(examples[0]),cnt)
            plt.xticks([], [])
            plt.yticks([], [])
            if j == 0:
                plt.ylabel(r"$\epsilon$ =  {}".format(epsilons[i]), fontdict = FONT_DICT)
            orig,adv,ex = examples[i][j]
            plt.title(r"{} $\rightarrow$ {}".format(orig, adv), fontdict = FONT_DICT)
            plt.imshow(ex, cmap = "gray")
    plt.tight_layout()
    plt.show()