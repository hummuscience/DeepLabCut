#
# DeepLabCut Toolbox (deeplabcut.org)
# © A. & M.W. Mathis Labs
# https://github.com/DeepLabCut/DeepLabCut
#
# Please see AUTHORS for contributors.
# https://github.com/DeepLabCut/DeepLabCut/blob/main/AUTHORS
#
# Licensed under GNU Lesser General Public License v3.0
#
"""File containing methods to load and parse shuffle metadata"""
from __future__ import annotations

import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from ruamel.yaml import YAML

from deeplabcut.core.engine import Engine
from deeplabcut.utils import auxiliaryfunctions


@dataclass(frozen=True)
class DataSplit:
    """Class representing the metadata for a shuffle"""
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        """
        Raises:
            ValueError if the indices are not sorted in increasing
        """
        for indices in [self.train_indices, self.test_indices]:
            idx = np.array(indices)
            if not np.all(idx[:-1] < idx[1:]):
                raise RuntimeError(
                    f"The training and test indices in a data split must be sorted in "
                    f"strictly ascending order."
                )


@dataclass(frozen=True)
class ShuffleMetadata:
    """Class representing the metadata for a shuffle"""
    name: str
    train_fraction: float
    index: int
    engine: Engine
    split: DataSplit | None

    def load_split(self, cfg: dict, trainset_path: Path) -> "ShuffleMetadata":
        """Loads the data split for this shuffle

        Args:
            cfg: the config for the DeepLabCut project
            trainset_path: the path to the training dataset folder

        Returns:
            a new instance with the data split defined
        """
        _, doc_path = auxiliaryfunctions.get_data_and_metadata_filenames(
            trainset_path, self.train_fraction, self.index, cfg
        )
        if not Path(doc_path).exists():
            raise ValueError(
                f"Could not load the metadata file for {self} as {doc_path} does not "
                f"exist. If you deleted the shuffle, you also need to delete the "
                f"shuffle from metadata.yaml or recreate the metadata.yaml file."
            )

        with open(doc_path, "rb") as f:
            _, train_idx, test_idx, _ = pickle.load(f)
        return ShuffleMetadata(
            name=self.name,
            train_fraction=self.train_fraction,
            index=self.index,
            engine=self.engine,
            split=DataSplit(
                train_indices=tuple(sorted([int(idx) for idx in train_idx])),
                test_indices=tuple(sorted([int(idx) for idx in test_idx])),
            )
        )


@dataclass(frozen=True)
class TrainingDatasetMetadata:
    """An immutable class containing the metadata for a dataset

    When creating a new "training-datasets" folder (e.g., when creating the first
    training set for a project, or when creating the first training for a given
    iteration of a project), TrainingDatasetMetadata.create(cfg) should be called when
    the "training-datasets" folder is still empty.

    For existing projects (created with DeepLabCut < 3.0), calling
    TrainingDatasetMetadata.create(cfg) will go over documentation data for all existing
    shuffles in the training-datasets folder and add them to a new metadata instance.
    All shuffles will be given Engine.TF as an engine.

    Examples:
        # Creating the metadata file for an existing project
        config = "/data/my-dlc-project/config.yaml"
        trainset_metadata = TrainingDatasetMetadata.create(config)
        trainset_metadata.save()

        # Adding a new shuffle to the metadata file
        config = "/data/my-dlc-project-2008-06-17/config.yaml"
        trainset_metadata = TrainingDatasetMetadata.load(config)
        new_shuffle = ShuffleMetadata(
            name="my-dlc-projectJun17-trainset60shuffle5",
            train_fraction=0.6,
            index=5,
            engine=compat.Engine.PYTORCH,
            split=DataSplit(train_indices=(1, 3, 4), test_indices=(0, 2)),
        )
        trainset_metadata = trainset_metadata.add(new_shuffle)
        trainset_metadata.save()  # saves to disk
    """
    project_config: dict
    shuffles: tuple[ShuffleMetadata, ...]
    file_header: tuple[str] = (
        "# This file is automatically generated - DO NOT EDIT",
        "# It contains the information about the shuffles created for the dataset",
        "---",
    )

    def __post_init__(self) -> None:
        """
        Raises:
            ValueError if the indices are not sorted in increasing order
        """
        indices = [[s.train_fraction, s.index] for s in self.shuffles]
        for (frac1, idx1), (frac2, idx2) in zip(indices[:-1], indices[1:]):
            if not (frac1 < frac2 or (frac1 == frac2 and idx1 < idx2)):
                raise RuntimeError(
                    "The shuffles given must be sorted in order of ascending training "
                    f"fraction and index. Found {self.shuffles}"
                )

    def add(
        self,
        shuffle: ShuffleMetadata,
        overwrite: bool = False,
    ) -> TrainingDatasetMetadata:
        """
        Adds a new shuffle to the metadata file

        Args:
            shuffle: the shuffle to add
            overwrite: if a shuffle with the same index is already stored in the
                metadata file, whether to overwrite it

        Returns:
            A new instance of TrainingDatasetMetadata with updated shuffles

        Raises:
            ValueError: if overwrite=False and there is already a shuffle with the given
                index in the metadata file.
        """
        existing_indices = [
            s.index for s in self.shuffles if s.train_fraction == shuffle.train_fraction
        ]
        if shuffle.index in existing_indices:
            if not overwrite:
                raise RuntimeError(
                    f"Cannot add {shuffle} to the meta: a shuffle with index "
                    f"{shuffle.index} and train_fraction {shuffle.train_fraction} "
                    f"already exists: {self.shuffles}."
                )

        existing_shuffles = [
            s
            for s in self.shuffles
            if (s.index != shuffle.index or s.train_fraction != shuffle.train_fraction)
        ]
        shuffles = existing_shuffles + [shuffle]
        return TrainingDatasetMetadata(
            project_config=self.project_config,
            shuffles=tuple(sorted(shuffles, key=lambda s: (s.train_fraction, s.index))),
        )

    def get(self, trainset_index: int = 0, index: int = 0) -> ShuffleMetadata:
        """
        Args:
            trainset_index: the index of the trainset fraction as defined in config.yaml
            index: the index of the shuffle

        Returns:
            the shuffle with the given trainset index and shuffle index

        Raises:
            ValueError if the shuffle is not present in the metadata
        """
        train_fraction = self.project_config["TrainingFraction"][trainset_index]
        for shuffle in self.shuffles:
            if (
                shuffle.train_fraction == train_fraction
                and shuffle.index == index
            ):
                return shuffle

        raise ValueError(
            f"Could not find a shuffle with trainingset fraction {train_fraction} and "
            f"index {index}"
        )

    def save(self) -> None:
        """Saves the training dataset metadata to disk"""
        metadata = {"shuffles": {}}
        data_splits: dict[DataSplit, int] = {}
        trainset_path = self.path(self.project_config).parent
        for s in self.shuffles:
            if s.split is None:
                s = s.load_split(cfg=self.project_config, trainset_path=trainset_path)

            split_index = data_splits.get(s.split)
            if split_index is None:
                split_index = len(data_splits) + 1
                data_splits[s.split] = split_index

            metadata["shuffles"][s.name] = {
                "train_fraction": s.train_fraction,
                "index": s.index,
                "split": split_index,
                "engine": s.engine.aliases[0],
            }

        with open(self.path(self.project_config), "w") as file:
            file.write("\n".join(self.file_header) + "\n")
            YAML().dump(metadata, file)

    @staticmethod
    def load(
        config: str | Path | dict,
        load_splits: bool = False,
    ) -> TrainingDatasetMetadata:
        """Loads the metadata from disk

        Args:
            config: the config for the DeepLabCut project (or its path)
            load_splits: whether to load the data split for each shuffle
        """
        if isinstance(config, (str, Path)):
            cfg = auxiliaryfunctions.read_config(config)
        else:
            cfg = config

        metadata_path = TrainingDatasetMetadata.path(cfg)
        with open(metadata_path, "r") as file:
            metadata = YAML(typ="safe", pure=True).load(file)

        shuffles = []
        for shuffle_name, shuffle_metadata in metadata["shuffles"].items():
            shuffle = ShuffleMetadata(
                name=shuffle_name,
                train_fraction=shuffle_metadata["train_fraction"],
                index=shuffle_metadata["index"],
                engine=Engine(shuffle_metadata["engine"]),
                split=None,
            )
            if load_splits:
                shuffle = shuffle.load_split(cfg, metadata_path.parent)

            shuffles.append(shuffle)

        shuffles.sort(key=lambda s: (s.train_fraction, s.index))
        return TrainingDatasetMetadata(project_config=cfg, shuffles=tuple(shuffles))

    @staticmethod
    def create(config: str | Path | dict) -> TrainingDatasetMetadata:
        """Function to create the metadata file

        Assumes that all existing shuffles use the TensorFlow engine, as this file
        should have already been created for PyTorch shuffles.

        Args;
            config: the config for the DeepLabCut project (or its path)
            default_engine: the default engine to set for shuffles in the project

        Returns:
            the metadata for the existing shuffles in the project
        """
        if isinstance(config, (str, Path)):
            cfg = auxiliaryfunctions.read_config(config)
        else:
            cfg = config

        trainset_path = TrainingDatasetMetadata.path(cfg).parent
        shuffle_docs = [
            f
            for f in trainset_path.iterdir()
            if re.match(r"Documentation_data-.+shuffle[0-9]+\.pickle", f.name)
        ]

        prefix = cfg["Task"] + cfg["date"]
        shuffles = []
        existing_splits: dict[tuple[tuple[int, ...], tuple[int, ...]], int] = {}
        for doc_path in shuffle_docs:
            index = int(doc_path.stem.split("shuffle")[-1])
            with open(doc_path, "rb") as f:
                _, train_idx, test_idx, train_frac = pickle.load(f)

            engine = Engine.TF
            train_idx = tuple(sorted([int(idx) for idx in train_idx]))
            test_idx = tuple(sorted([int(idx) for idx in test_idx]))
            split_idx = existing_splits.get((train_idx, test_idx))
            if split_idx is None:
                split_idx = len(existing_splits) + 1
                existing_splits[(train_idx, test_idx)] = split_idx

            shuffles.append(
                ShuffleMetadata(
                    name=f"{prefix}-trainset{int(100 * train_frac)}shuffle{index}",
                    train_fraction=train_frac,
                    index=index,
                    engine=engine,
                    split=DataSplit(train_indices=train_idx, test_indices=test_idx),
                )
            )

        shuffles = tuple(sorted(shuffles, key=lambda s: (s.train_fraction, s.index)))
        return TrainingDatasetMetadata(
            project_config=cfg,
            shuffles=shuffles,
        )

    @staticmethod
    def path(cfg: dict) -> Path:
        """
        Args:
            cfg: the config for the DeepLabCut project

        Returns:
            the path to the training dataset metadata file
        """
        meta_path = auxiliaryfunctions.get_training_set_folder(cfg) / "metadata.yaml"
        return Path(cfg["project_path"]) / meta_path


def update_metadata(
    cfg: dict,
    train_fraction: float,
    shuffle: int,
    engine: Engine,
    train_indices: list[int],
    test_indices: list[int],
    overwrite: bool = False,
) -> None:
    """Updates the metadata for a training-dataset

    Args:
        cfg: the config for the DeepLabCut project
        train_fraction: the train_fraction of the new shuffle
        shuffle: the index of the shuffle to add
        engine: the engine for the shuffle
        train_indices: the indices of images in the training set
        test_indices: the indices of images in the test set
        overwrite: whether to overwrite a shuffle with the same index and train fraction
            if one exists

    Raises:
        ValueError: if overwrite=False and there is already a shuffle with the given
            index in the metadata file.
    """
    prefix = cfg["Task"] + cfg["date"]
    metadata = TrainingDatasetMetadata.load(cfg, load_splits=True)
    new_shuffle = ShuffleMetadata(
        name=f"{prefix}-trainset{int(100 * train_fraction)}shuffle{shuffle}",
        train_fraction=train_fraction,
        index=shuffle,
        engine=engine,
        split=DataSplit(
            train_indices=tuple(sorted([int(i) for i in train_indices])),
            test_indices=tuple(sorted([int(i) for i in test_indices])),
        )
    )
    metadata = metadata.add(shuffle=new_shuffle, overwrite=overwrite)
    metadata.save()


def get_shuffle_engine(
    cfg: dict,
    trainingsetindex: int,
    shuffle: int,
    modelprefix: str = "",
) -> Engine:
    """
    Args:
        cfg: the config for the DeepLabCut project
        trainingsetindex: the training set index used
        shuffle: the shuffle for which to get the engine
        modelprefix: the model prefix, if there is one

    Returns:
        the engine that the shuffle was created with

    Raises:
        ValueError if the engine for the shuffle cannot be determined or the shuffle
        doesn't exist
    """
    if not TrainingDatasetMetadata.path(cfg).exists():
        metadata = TrainingDatasetMetadata.create(cfg)
        metadata.save()

    metadata = TrainingDatasetMetadata.load(cfg)
    shuffle_metadata = metadata.get(trainingsetindex, shuffle)
    if modelprefix:
        # try to get the engine by checking which models folder exists
        engines = find_engines_from_model_folders(
            cfg, trainingsetindex, shuffle, modelprefix
        )
        if len(engines) == 0:
            raise ValueError(
                f"Couldn't find any shuffles with trainingsetindex={trainingsetindex}, "
                f"shuffle={shuffle} and modelprefix={modelprefix}. Please check that "
                f"such a shuffle is defined."
            )

        if len(engines) == 1:
            return engines.pop()

        if shuffle_metadata.engine in engines:
            engine = shuffle_metadata.engine
        else:
            engine = engines.pop()  # take a random engine

        logging.warning(
            f"Found multiple engines for trainingsetindex={trainingsetindex}, "
            f"shuffle={shuffle} and modelprefix={modelprefix}. Using engine={engine}. "
            f"To select another engine, please specify it in your API call."
        )
        return engine

    return shuffle_metadata.engine


def find_engines_from_model_folders(
    cfg: dict,
    trainingsetindex: int,
    shuffle: int,
    modelprefix: str = "",
) -> set[Engine]:
    """Determines which engines are used with a given shuffle.

    This method can be useful when using modelprefix, as the engine for a shuffle stored
    under a "modelprefix" might not be the same as the base shuffle (for which the
    engine is stored in the training-datasets folder).

    Args:
        cfg: the config for the DeepLabCut project
        trainingsetindex: the training set index used
        shuffle: the shuffle for which to get the engine
        modelprefix: the model prefix, if there is one

    Returns:
        the engines for which a model folder exists for the given shuffle
    """
    project_path = Path(cfg["project_path"])
    train_fraction = cfg["TrainingFraction"][trainingsetindex]

    existing_engines = set()
    for engine in Engine:
        expected_model_folder = project_path / auxiliaryfunctions.get_model_folder(
            trainFraction=train_fraction,
            shuffle=shuffle,
            cfg=cfg,
            engine=engine,
            modelprefix=modelprefix,
        )
        if expected_model_folder.exists():
            existing_engines.add(engine)

    return existing_engines
