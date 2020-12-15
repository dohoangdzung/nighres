import nibabel as nb
import numpy as np
import time
import inspect
import json
import os
from io import BytesIO
from gzip import GzipFile


def load_volume(volume, log_file="timelog.json"):
    """
    Load volumetric data into a
    `Nibabel SpatialImage <http://nipy.org/nibabel/reference/nibabel.spatialimages.html#nibabel.spatialimages.SpatialImage>`_

    Parameters
    ----------
    volume: niimg
        Volumetric data to be loaded, can be a path to a file that nibabel can
        load, or a Nibabel SpatialImage

    Returns
    ----------
    image: Nibabel SpatialImage

    Notes
    ----------
    Originally created as part of Laminar Python [1]_ .

    References
    -----------
    .. [1] Huntenburg et al. (2017), Laminar Python: Tools for cortical
       depth-resolved analysis of high-resolution brain imaging data in
       Python. DOI: 10.3897/rio.3.e12346
    """  # noqa

    # if input is a filename, try to load it
    # python 2 version if isinstance(volume, basestring):


    if isinstance(volume, str):
        start = time.time()
        # importing nifti files
        # image = nb.load(volume) # disable lazy-load
        # Read from file instead
        with open(volume, "rb") as in_file:
            fh = nb.FileHolder(fileobj=GzipFile(fileobj=BytesIO(in_file.read())))
            image = nb.Nifti1Image.from_file_map({"header": fh, "image": fh})
        end = time.time()

        caller_function = str(inspect.stack()[1].function)
        time_log(log_file, caller_function, "read", volume, start, end)
    # if volume is already a nibabel object
    elif isinstance(volume, nb.spatialimages.SpatialImage):
        image = volume
    else:
        raise ValueError('Input volume must be a either a path to a file in a '
                         'format that Nibabel can load, or a nibabel'
                         'SpatialImage.')

    return image


def save_volume(filename, volume, dtype='float32', overwrite_file=True, log_file="timelog.json"):
    """
    Save volumetric data that is a
    `Nibabel SpatialImage <http://nipy.org/nibabel/reference/nibabel.spatialimages.html#nibabel.spatialimages.SpatialImage>`_
    to a file

    Parameters
    ----------
    filename: str
        Full path and filename under which volume should be saved. The
        extension determines the file format (must be supported by Nibabel)
    volume: Nibabel SpatialImage
        Volumetric data to be saved
    dtype: str, optional
        Datatype in which volumetric data should be stored (default is float32)
    overwrite_file: bool, optional
        Overwrite existing files (default is True)

    Notes
    ----------
    Originally created as part of Laminar Python [1]_ .

    References
    -----------
    .. [1] Huntenburg et al. (2017), Laminar Python: Tools for cortical
       depth-resolved analysis of high-resolution brain imaging data in
       Python. DOI: 10.3897/rio.3.e12346
    """  # noqa
    import os
    start = time.time()
    if dtype is not None:
        volume.set_data_dtype(dtype)
    if os.path.isfile(filename) and overwrite_file is False:
        print("\nThis file exists and overwrite_file was set to False, "
              "file not saved.")
    else:
        try:
            volume.to_filename(filename)
            print("\nSaving {0}".format(filename))
        except AttributeError:
            print('\nInput volume must be a Nibabel SpatialImage.')

    end = time.time()
    caller_function = str(inspect.stack()[1].function)
    time_log(log_file, caller_function, "write", filename, start, end)


def time_log(log_file, task_name, op_name, filename, start, end):
    # Create log file if not exists
    if not os.path.exists(log_file):
        with open(log_file, 'w+') as logfile:
            logfile.write("{}")

    # Save time log to json object
    with open(log_file, "r") as logfile:
        log = json.load(logfile)

    if task_name not in log:
        log[task_name] = {}

    if op_name not in log[task_name]:
        log[task_name][op_name] = []

    if (filename is not None) and (filename is not "") and (os.stat(filename) is not None):
        filesize = os.stat(filename).st_size
    else:
        filesize = 0
    log[task_name][op_name].append({"filename": filename,
                                    "filesize": filesize,
                                    "start": start,
                                    "end": end,
                                    "duration": end-start})

    with open(log_file, "w") as logfile:
        json.dump(log, logfile)
