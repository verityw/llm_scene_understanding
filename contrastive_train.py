import os
import pickle
from tqdm import tqdm, trange
import numpy as np
import matplotlib.pyplot as plt

import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import datasets
from torchvision.transforms import ToTensor
import torch.nn.functional as F

from dataset import FinetuningDataset
from models import ContrastiveNet, FeedforwardNet


def train_job(lm, label_set, epochs, batch_size, co_suffix="", seed=0):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    # Create datasets
    ds = FinetuningDataset(lm, label_set, co_suffix)
    train_ds, val_ds, test_ds = ds.create_split(0.4, 0.2)

    # Create dataloaders
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=True)
    test_dl = DataLoader(test_ds, batch_size=batch_size, shuffle=True)

    embedding_size = 256
    query_net = FeedforwardNet(1024, embedding_size)  # TODO: Try other values
    label_net = FeedforwardNet(1024, embedding_size)  # TODO: Try other values
    query_net.to(device)
    label_net.to(device)

    label_embeddings = torch.load("./label_embeddings/" + lm + ".pt")

    # Current best: 0.7018 - LR=0.00001, WD=0.0001, SS=20, G=0.99
    params = params = list(query_net.parameters()) + list(
        label_net.parameters())
    optimizer = torch.optim.Adam(params, lr=0.00001, weight_decay=0.001)

    def contrastive_loss(pred, labels):
        return F.cross_entropy(pred, labels)

    loss_fxn = contrastive_loss
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer,
                                                step_size=20,
                                                gamma=0.9)

    train_losses = []
    val_losses = []
    train_acc = []
    val_acc = []

    desc = ""
    torch.manual_seed(seed)
    with trange(epochs) as pbar:
        for epoch in pbar:
            train_epoch_loss = []
            val_epoch_loss = []
            train_epoch_acc = []
            val_epoch_acc = []
            for batch_idx, (query_em, _, label) in enumerate(train_dl):
                embed1 = query_net(query_em)
                embed2 = label_net(label_embeddings)
                pred = embed1 @ embed2.T

                loss = loss_fxn(pred, label)

                loss.backward()
                optimizer.step()
                train_epoch_loss.append(loss.item())

                accuracy = ((torch.argmax(pred, dim=1) == label) * 1.0).mean()
                train_epoch_acc.append(accuracy)

                if batch_idx % 100 == 0:
                    pbar.set_description((desc).rjust(20))

            scheduler.step()
            train_losses.append(torch.mean(torch.tensor(train_epoch_loss)))
            train_acc.append(torch.mean(torch.tensor(train_epoch_acc)))

            for batch_idx, (query_em, _, label) in enumerate(val_dl):
                with torch.no_grad():
                    embed1 = query_net(query_em)
                    embed2 = label_net(label_embeddings)
                    pred = embed1 @ embed2.T

                    loss = loss_fxn(pred, label)
                    val_epoch_loss.append(loss.item())

                    accuracy = ((torch.argmax(pred, dim=1) == label) *
                                1.0).mean()
                    val_epoch_acc.append(accuracy)
                    if batch_idx % 100 == 0:
                        desc = (f"{np.mean(np.array(train_epoch_loss)):6.4}" +
                                ", " + f"{accuracy.item():6.4}")
                        pbar.set_description((desc).rjust(20))
            val_losses.append(torch.mean(torch.tensor(val_epoch_loss)))
            val_acc.append(torch.mean(torch.tensor(val_epoch_acc)))

    test_loss, test_acc = [], []
    for batch_idx, (query_em, _, label) in enumerate(test_dl):
        with torch.no_grad():
            embed1 = query_net(query_em)
            embed2 = label_net(label_embeddings)
            pred = embed1 @ embed2.T

            loss = loss_fxn(pred, label)
            test_loss.append(loss.item())

            accuracy = ((torch.argmax(pred, dim=1) == label) * 1.0).mean()
            test_acc.append(accuracy)

    print("test loss:", torch.mean(torch.tensor(test_loss)))
    print("test acc:", torch.mean(torch.tensor(test_acc)))

    return train_losses, val_losses, train_acc, val_acc, test_loss, test_acc


if __name__ == "__main__":
    # train_job("RoBERTa-large", "nyuClass", 100, 512, co_suffix="")
    (
        train_losses_list,
        val_losses_list,
        train_acc_list,
        val_acc_list,
        test_loss_list,
        test_acc_list,
    ) = (
        [],
        [],
        [],
        [],
        [],
        [],
    )

    for lm in ["RoBERTa-large", "BERT-large"]:
        for label_set in ["nyuClass", "mpcat40"]:
            for use_gt in [True, False]:
                print("Starting:", lm, label_set, "use_gt =", use_gt)
                co_suffix = "" if use_gt else "_gpt_j_co"
                (
                    train_losses,
                    val_losses,
                    train_acc,
                    val_acc,
                    test_loss,
                    test_acc,
                ) = train_job(lm, label_set, 100, 512, co_suffix=co_suffix)
                train_losses_list.append(train_losses)
                val_losses_list.append(val_losses)
                train_acc_list.append(train_acc)
                val_acc_list.append(val_acc)
                test_loss_list.append(test_loss)
                test_acc_list.append(test_acc)

    pickle.dump(train_losses_list,
                open("./contrastive_results/train_losses.pkl", "wb"))
    pickle.dump(train_acc_list,
                open("./contrastive_results/train_acc.pkl", "wb"))
    pickle.dump(val_losses_list,
                open("./contrastive_results/val_losses.pkl", "wb"))
    pickle.dump(val_acc_list, open("./contrastive_results/val_acc.pkl", "wb"))
    pickle.dump(test_loss_list,
                open("./contrastive_results/test_loss.pkl", "wb"))
    pickle.dump(test_acc_list, open("./contrastive_results/test_acc.pkl",
                                    "wb"))
