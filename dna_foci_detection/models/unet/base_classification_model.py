from pytorch_lightning import LightningModule
import torch as t
import torch.nn.functional as F
from argparse import Namespace

import matplotlib.pyplot as plt
import ipdb
import os
import mate
import numpy as np
import cv2 as cv


def max_distance(coords, debug=False):
    max_x = t.max(coords[0])
    max_y = t.max(coords[1])
    min_x = t.min(coords[0])
    min_y = t.min(coords[1])
    return np.sqrt((max_x - min_x) ** 2 + (max_y - min_y) ** 2)


def draw_label_img(label_img, img, color=(1, 0, 1)):
    label_img = label_img.squeeze(0)
    values = np.unique(label_img)
    labels = []
    for value in values:
        if value == 0:
            continue
        value_labels = []
        labels.append(value_labels)
        for i in range(label_img.shape[0]):
            for j in range(label_img.shape[1]):
                if label_img[i, j] == value:
                    value_labels.append([i, j, 1])
    foci = []
    for label in labels:
        label = t.tensor(label).T.float()
        label_means = t.mean(label, dim=1)
        r = max_distance(label) / 2
        if r > 0:
            label_means[-1] = r
            foci.append([label_means[0], label_means[1], label_means[2]])
    labels = t.tensor(foci)
    if len(labels) > 0:
        return draw_label(labels, img, color)
    return img


def draw_label(raw_label, img, color=(1, 1, 1)):
    label = raw_label.clone()
    label = t.round(label).int().tolist()
    img = np.array(img.tolist())
    for x, y, r in label:
        img = cv.circle(img, (y, x), radius=r, color=color, thickness=1)
    return img


def watershed_label(image):
    from scipy import ndimage as ndi
    from skimage.segmentation import watershed
    from skimage.feature import peak_local_max

    # Now we want to separate the two objects in image
    # Generate the markers as local maxima of the distance to the background
    image = image.astype(int)
    distance = ndi.distance_transform_edt(image)
    coords = peak_local_max(distance, footprint=np.ones((3, 3)), labels=image)
    mask = np.zeros(distance.shape, dtype=bool)
    mask[tuple(coords.T)] = True
    markers, _ = ndi.label(mask)
    labels = watershed(-distance, markers, mask=image)
    return t.from_numpy(labels)


def visualize_predictions(
    imgs, labels, pred_labels, save_path: str, epoch=-1, plot=False
):
    # fig, axes = plt.subplots(1, 2)
    # axes[0].imshow(img.permute(1, 2, 0))
    # axes[1].imshow(mask_from_label(labels))
    # ipdb.set_trace()
    indices = [i for i in range(len(labels)) if (labels[i] > 0).any()][:2]
    if len(indices) < 2:
        return
    fig, axes = plt.subplots(nrows=1, ncols=len(indices))
    for index, i in enumerate(indices):
        img = imgs[i]
        label = labels[i]
        pred_label = pred_labels[i]
        img = img.permute(1, 2, 0)
        # pred_labels = pred_labels[pred_labels[:, 0] >= 0.5]
        # print(f"{img.shape=}")
        # print(f"{img.shape=}")
        sharpened_label = label[0].detach().cpu().numpy()
        sharpened_label = watershed_label(sharpened_label)

        sharpened_disc_label = (
            (pred_label[0].detach().cpu() > 0.5).float().numpy()
        )
        sharpened_pred_label = watershed_label(sharpened_disc_label)
        img = t.from_numpy(
            draw_label_img(
                sharpened_pred_label.cpu(), img.cpu().numpy(), color=(1, 0, 1)
            )
        )
        img = t.from_numpy(
            draw_label_img(
                sharpened_label.cpu(), img.cpu().numpy(), color=(0, 1, 0)
            )
        )
        # ax = axes[0][index]
        fig = axes[index].imshow(img)
        fig.axes.get_xaxis().set_visible(False)
        fig.axes.get_yaxis().set_visible(False)
        # axes[index].set_title(f"")
        """

        ax = axes[1][index]
        fig = ax.imshow(sharpened_disc_label)
        fig.axes.get_xaxis().set_visible(False)
        fig.axes.get_yaxis().set_visible(False)
        ax.set_title(f"Disc")

        ax = axes[2][index]
        fig = ax.imshow(sharpened_pred_label)
        fig.axes.get_xaxis().set_visible(False)
        fig.axes.get_yaxis().set_visible(False)
        ax.set_title(f"Sharpened predicted")

        ax = axes[3][index]
        fig = ax.imshow(sharpened_label)
        fig.axes.get_xaxis().set_visible(False)
        fig.axes.get_yaxis().set_visible(False)
        ax.set_title(f"Sharpened original")
        """

    plt.axis("off")
    plt.tight_layout()
    plt.suptitle(f"Epoch {epoch}, Green = true label")
    plt.savefig(save_path, dpi=500) if not plot else plt.show()
    plt.clf()
    plt.close()


class Model(LightningModule):
    def __init__(self, params: Namespace):
        super().__init__()
        self.params = params
        self.classifier: t.nn.Module
        self.criterion = t.nn.BCELoss()
        self.loss = lambda x, y: self.criterion(x.flatten(), y.flatten())
        self.best_loss = float("inf")

    def forward(self, z: t.Tensor) -> t.Tensor:
        out = self.classifier(z)
        return out

    def training_step(self, batch: tuple[t.Tensor, t.Tensor], batch_idx: int):
        x, labels = batch
        y_pred = self.classifier(x)
        loss = self.loss(y_pred, labels)
        if batch_idx == 0:
            print(f"{y_pred.max().item()=} {y_pred.min().item()=}")
            """
            visualize_predictions(
                x,
                labels,
                y_pred,
                os.path.join(self.params.save_path, "train_pred.png"),
                epoch=self.current_epoch,
            )
            print("visualized!!")
            """
        return {"loss": loss}

    def training_epoch_end(self, outputs):
        avg_loss = t.stack([x["loss"] for x in outputs]).mean()
        self.log("train_loss", avg_loss, prog_bar=True)

    def validation_step(
        self, batch: tuple[t.Tensor, t.Tensor], batch_idx: int
    ):
        x, labels = batch
        y_pred = self.classifier(x)
        loss = self.loss(y_pred, labels)
        if batch_idx == 0:
            visualize_predictions(
                x,
                labels,
                y_pred,
                os.path.join(self.params.save_path, "val_pred.png"),
                epoch=self.current_epoch,
            )
        return {
            "val_loss": loss,
        }

    def validation_epoch_end(self, outputs):
        avg_loss = t.stack([x["val_loss"] for x in outputs]).mean()
        if avg_loss < self.best_loss:
            self.best_loss = avg_loss
            print("Model reached new best. Saving it.")
            for torch_model_name in self.params.model:
                with open(
                    os.path.join(
                        self.params.save_path,
                        "checkpoint",
                        torch_model_name + ".pt",
                    ),
                    "wb",
                ) as f:
                    t.save(self.__getattr__(torch_model_name).state_dict(), f)
        self.log("val_loss", avg_loss, prog_bar=True)
        return {"val_loss": avg_loss}

    def test_step(self, batch: tuple[t.Tensor, t.Tensor], batch_idx: int):

        x, labels = batch
        y_pred = self.classifier(x)
        loss = self.loss(y_pred, labels)
        if batch_idx == 0:
            visualize_predictions(
                x,
                labels,
                y_pred,
                os.path.join(self.params.save_path, "test_pred.png"),
                epoch=self.current_epoch,
                # plot=True,
            )
        return {
            "test_loss": loss,
        }

    def test_epoch_end(self, outputs):
        avg_loss = t.stack([x["test_loss"] for x in outputs]).mean()
        return {"test_loss": avg_loss}

    def configure_optimizers(self):
        return mate.Optimizer(
            self.params.configure_optimizers, self.classifier
        )()
