import os
import re
import h5py
import numpy as np
import torch.utils.data as data
from PIL import Image

import pyvista as pv


class KITTIDetection(data.Dataset):
    """The KITTI Detection dataset.

    Args:
      root (string): Root directory of the KITTI dataset.
      split (string, optional): The dataset subset which can be either
        "train", "val", or "test". Default: ``"train"``.
      transforms (callable, optional): A function/transform that takes
        input sample and its target as entry and return a transformed
        version. Default: ``None``.
      rectified (bool, optional): If True, return the LiDAR point cloud
        in the camera rectified coordinate system. Default: ``True``.
    """  # noqa

    def __init__(self, root, split="train", transforms=None, rectified=True):
        super(KITTIDetection, self).__init__()
        self.root = root
        if split in ["train", "val"]:
            self.split = "training"
        else:
            self.split = "testing"
        self.transforms = transforms
        self.rectified = rectified

        self.image_path = os.path.join(root, self.split, "image_2")
        self.lidar_path = os.path.join(root, self.split, "velodyne")
        self.label_path = os.path.join(root, self.split, "label_2")
        self.calib_path = os.path.join(root, self.split, "calib")

        if not self._check_integrity():
            raise RuntimeError("Dataset not found or corrupted.")

        self.framelist = sorted(
            [
                int(x.split(".")[0])
                for x in os.listdir(self.lidar_path)
                if re.match("^[0-9]{6}.bin$", x)
            ]
        )

    @staticmethod
    def lidar_to_rect(lidar, calib):
        n = lidar.shape[0]
        xyzw = np.c_[lidar[:, 0:3], np.ones(n)]
        xyz = np.dot(xyzw, np.dot(calib["velo_to_cam"].T, calib["R0"].T))
        intensity = lidar[:, 3]
        return np.c_[xyz, intensity]

    def _check_integrity(self):
        return (
            os.path.exists(self.image_path)
            and os.path.exists(self.calib_path)
            and os.path.exists(self.lidar_path)
            and (os.path.exists(self.label_path) if self.split == "training" else True)
        )

    def __len__(self):
        return len(self.framelist)

    def __getitem__(self, i):
        frameid = self.framelist[i]
        image = self._get_image(frameid)
        lidar = self._get_lidar(frameid)
        calib = self._get_calib(frameid)
        target = None
        if self.split == "training":
            target = self._get_label(frameid)

        if self.rectified:
            lidar = self.lidar_to_rect(lidar, calib)

        inputs = {"image": image, "lidar": lidar, "calib": calib}
        if self.transforms is not None:
            inputs, target = self.transforms(inputs, target)
        return inputs, target

    def _get_image(self, frameid):
        basename = "{:06d}.png".format(frameid)
        filename = os.path.join(self.image_path, basename)
        image = Image.open(filename)
        return image

    def _get_lidar(self, frameid):
        basename = "{:06d}.bin".format(frameid)
        filename = os.path.join(self.lidar_path, basename)
        lidar = np.fromfile(filename, dtype=np.float32).reshape(-1, 4)
        return lidar

    def _get_calib(self, frameid):
        basename = "{:06d}.txt".format(frameid)
        filename = os.path.join(self.calib_path, basename)
        return self.parse_kitti_calib(filename)

    def _get_label(self, frameid):
        basename = "{:06d}.txt".format(frameid)
        filename = os.path.join(self.label_path, basename)
        return self.parse_kitti_label(filename)

    def parse_kitti_calib(self, filename):
        calib = {}
        with open(filename, "r") as fp:
            lines = [line.strip().split(" ") for line in fp.readlines()]
        calib["P0"] = np.array([float(x) for x in lines[0][1:13]])
        calib["P1"] = np.array([float(x) for x in lines[1][1:13]])
        calib["P2"] = np.array([float(x) for x in lines[2][1:13]])
        calib["P3"] = np.array([float(x) for x in lines[3][1:13]])
        calib["R0"] = np.array([float(x) for x in lines[4][1:10]])
        calib["velo_to_cam"] = np.array([float(x) for x in lines[5][1:13]])
        calib["imu_to_velo"] = np.array([float(x) for x in lines[6][1:13]])
        calib["P0"] = calib["P0"].reshape(3, 4)
        calib["P1"] = calib["P1"].reshape(3, 4)
        calib["P2"] = calib["P2"].reshape(3, 4)
        calib["P3"] = calib["P3"].reshape(3, 4)
        calib["R0"] = calib["R0"].reshape(3, 3)
        calib["velo_to_cam"] = calib["velo_to_cam"].reshape(3, 4)
        calib["imu_to_velo"] = calib["imu_to_velo"].reshape(3, 4)
        return calib

    def parse_kitti_label(self, filename):
        annotations = {
            "class": [],
            "truncated": [],
            "occluded": [],
            "alpha": [],
            "bbox": [],
            "size": [],
            "center": [],
            "yaw": [],
        }
        with open(filename, "r") as fp:
            lines = [line.strip().split(" ") for line in fp.readlines()]
        annotations["class"] = np.array([x[0] for x in lines])
        annotations["truncated"] = np.array([float(x[1]) for x in lines])
        annotations["occluded"] = np.array([int(x[2]) for x in lines])
        annotations["alpha"] = np.array([float(x[3]) for x in lines])
        annotations["bbox"] = np.array([[float(v) for v in x[4:8]] for x in lines])
        annotations["size"] = np.array([[float(v) for v in x[8:11]] for x in lines])
        annotations["center"] = np.array([[float(v) for v in x[11:14]] for x in lines])
        annotations["yaw"] = np.array([float(x[14]) for x in lines])
        annotations["bbox"] = annotations["bbox"].reshape(-1, 4)
        annotations["size"] = annotations["size"].reshape(-1, 3)
        annotations["center"] = annotations["center"].reshape(-1, 3)
        annotations["yaw"] = annotations["yaw"].reshape(-1)
        return annotations


if __name__ == "__main__":
    dataset = KITTIDetection("data/KITTI", rectified=True)

    pv.set_plot_theme("night")
    for inputs, target in dataset:
        lidar = inputs["lidar"]
        plt = pv.Plotter()
        mesh = pv.PolyData(lidar[:, 0:3])
        mesh["intensity"] = lidar[:, 3]
        plt.add_mesh(mesh, render_points_as_spheres=True, cmap="viridis")
        plt.add_axes_at_origin()

        def roty(angle):
            c = np.cos(angle)
            s = np.sin(angle)
            return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

        for i in range(len(target["class"])):
            if target["class"][i] == "DontCare":
                continue

            print(target["class"][i])
            R = roty(target["yaw"][i])
            h, w, l = target["size"][i, 0:3]
            x = [l / 2, l / 2, -l / 2, -l / 2, l / 2, l / 2, -l / 2, -l / 2]
            y = [0, 0, 0, 0, -h, -h, -h, -h]
            z = [w / 2, -w / 2, -w / 2, w / 2, w / 2, -w / 2, -w / 2, w / 2]
            obb = np.vstack([x, y, z])
            obb = np.dot(R, np.vstack([x, y, z]))
            obb = obb.T + target["center"][i]

            bounds = np.c_[np.amin(obb, axis=0), np.amax(obb, axis=0)]
            bounds = np.ravel(bounds, order="C")
            box = pv.Box(bounds)
            plt.add_mesh(box, style="wireframe", line_width=8.0)

        plt.enable_eye_dome_lighting()
        plt.show()
        plt.close()

        break
