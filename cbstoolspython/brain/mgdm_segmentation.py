import numpy as np
import nibabel as nb
import os
import sys
import cbstools
from ..io import load_volume, save_volume
from ..utils import _output_dir_4saving, _fname_4saving

# TODO
ATLAS_DIR = '/home/julia/workspace/cbstools-python/atlases/brain-segmentation-prior3.0/'
TOPOLOGY_LUT_DIR = '/home/julia/workspace/cbstools-python/lut/'
DEFAULT_ATLAS = os.path.join(ATLAS_DIR, "brain-atlas-3.0.3.txt")


def _get_mgdm_orientation(affine, mgdm):
    '''
    Transforms nibabel affine information into
    orientation and slice order that MGDM understands
    '''
    orientation = nb.aff2axcodes(affine)
    # set mgdm slice order
    # TODO how clean is this?
    if orientation[-1] == "I" or orientation[-1] == "S":
        sliceorder = mgdm.AXIAL
    elif orientation[-1] == "L" or orientation[-1] == "R":
        sliceorder = mgdm.SAGITTAL
    else:
        sliceorder = mgdm.CORONAL

    # set mgdm orientations
    if "L" in orientation:
        LR = mgdm.R2L
    elif "R" in orientation:
        LR = mgdm.L2R  # flipLR = True
    if "A" in orientation:
        AP = mgdm.P2A  # flipAP = True
    elif "P" in orientation:
        AP = mgdm.A2P
    if "I" in orientation:
        IS = mgdm.S2I  # flipIS = True
    elif "S" in orientation:
        IS = mgdm.I2S

    return sliceorder, LR, AP, IS


def _get_mgdm_intensity_priors(atlas_file):
    """
    Returns a list of available as intensity priors
    in the MGDM atlas that you are using
    """
    priors = []
    with open(atlas_file) as fp:
        for i, line in enumerate(fp):
            if "Structures:" in line:  # this is the beginning of the LUT
                lut_idx = i
                lut_rows = map(int, [line.split()[1]])[0]
            if "Intensity Prior:" in line:
                priors.append(line.split()[-1])
    return priors


def mgdm_segmentation(contrast_image1, contrast_type1,
                      contrast_image2=None, contrast_type2=None,
                      contrast_image3=None, contrast_type3=None,
                      contrast_image4=None, contrast_type4=None,
                      n_steps=5, topology='wcs',
                      atlas_file=None, topology_lut_dir=None,
                      adjust_intensity_priors=False,
                      compute_posterior=False,
                      diffuse_probabilities=False,
                      save_data=False, output_dir=None,
                      file_name=None, file_extension=None):
    """ MGDM segmentation

    Estimate brain structures from an atlas for MRI dataset using
    a Multiple Object Geometric Deformable Model (MGDM) [1,2]

    Parameters
    ----------
    contrast_image1: TODO:type
        First input image to perform segmentation on
    contrast_type1: str
        Contrast type of first input image, must be listed as a prior in used
        atlas(specified in atlas_file)
    contrast_image2: TODO:type, optional
        Additional input image to inform segmentation, must be in the same
        space as constrast_image1, requires contrast_type2
    contrast_type2: str, optional
        Contrast type of second input image, must be listed as a prior in used
        atlas (specified in atlas_file)
    contrast_image3: TODO:type, optional
        Additional input image to inform segmentation, must be in the same
        space as constrast_image1, requires contrast_type3
    contrast_type3: str, optional
        Contrast type of third input image, must be listed as a prior in used
        atlas (specified in atlas_file)
    contrast_image4: TODO:type, optional
        Additional input image to inform segmentation, must be in the same
        space as constrast_image1, requires contrast_type4
    contrast_type4: str, optional
        Contrast type of fourth input image, must be listed as a prior in used
        atlas (specified in atlas_file)
    n_steps: int, optional
        Number of steps for MGDM (default is 5, set to 0 for quick testing of
        registration of priors, which does not perform true segmentation)
    topology: {'wcs', 'no'}, optional
        Topology setting, choose 'wcs' (well-composed surfaces) for strongest
        topology constraint, 'no' for no topology constraint (default is 'wcs')
    atlas_file: str, optional
        Path to plain text atlas file (default is stored in DEFAULT_ATLAS)
    topology_lut_dir: str, optional
        Path to directory in which topology files are stored (default is stored
        in TOPOLOGY_LUT_DIR)
    adjust_intensity_priors: bool
        Adjust intensity priors based on dataset (default is False)
    compute_posterior: bool
        Compute posterior probabilities for segmented structures
        (default is False)
    diffuse_probabilities: bool
        Regularize probability distribution with a non-linear diffusion scheme
        (default is False)
    save_data: bool
        Save output data to file (default is False)
    output_dir: str, optional
        Path to desired output directory, will be created if it doesn't exist
    file_name: str, optional
        Desired base name for output files (suffixes will be added)
    file_extension: str, optional
        Desired extension for output files (determines file type)

    Returns
    ----------
    outputs: dict
        Dictionary collecting outputs under the following keys
        - 'segmentation': Hard brain segmentation (_mgdm_seg)
        - 'labels': Maximum tissue probability labels (_mgdm_lbls)
        - 'memberships': Maximum tissue probability values (_mgdm_mems)
        - 'distance': Minimum distance to a segmentation boundary (_mgdm_dist)
        (suffix of output files if save_data is set to True)

    References
    ----------
    [1] Bogovic, Prince and Bazin (2013). A multiple object geometric
    deformable model for image segmentation. DOI: 10.1016/j.cviu.2012.10.006.A
    [2] Fan, Bazin and Prince (2008). A multi-compartment segmentation
    framework with homeomorphic level sets. DOI: 10.1109/CVPR.2008.4587475
    """

    # set default atlas if not given
    # TODO search given atlas file in default atlas dir?
    if atlas_file is None:
        atlas_file = DEFAULT_ATLAS

    # set default topology lut dir if not given
    if topology_lut_dir is None:
        topology_lut_dir = TOPOLOGY_LUT_DIR
    else:
        # if we don't end in a path sep, we need to make sure that we add it
        if not(topology_lut_dir[-1] == os.path.sep):
            topology_lut_dir += os.path.sep

    # find available intensity priors in selected MGDM atlas
    mgdm_intensity_priors = _get_mgdm_intensity_priors(atlas_file)

    # sanity check contrast types
    contrasts = [contrast_image1, contrast_image2,
                 contrast_image3, contrast_image4]
    ctypes = [contrast_type1, contrast_type2, contrast_type3, contrast_type4]
    for idx, ctype in enumerate(ctypes):
        if ctype is None and contrasts[idx] is not None:
            raise ValueError(("If specifying contrast_image{0}, please also "
                              "specify contrast_type{0}".format(idx+1, idx+1)))

        elif ctype is not None and ctype not in mgdm_intensity_priors:
            raise ValueError(("{0} is not a valid contrast type for  "
                              "contrast_type{1} please choose from the "
                              "following contrasts provided by the chosen "
                              "atlas: ").format(ctype, idx+1),
                             ", ".join(mgdm_intensity_priors))

    # start virtual machine, if not already running
    try:
        cbstools.initVM(initialheap='6000m', maxheap='6000m')
    except ValueError:
        pass
    # create mgdm instance
    mgdm = cbstools.BrainMgdmMultiSegmentation2()

    # set mgdm parameters
    mgdm.setAtlasFile(atlas_file)
    mgdm.setTopologyLUTdirectory(topology_lut_dir)
    mgdm.setOutputImages('segmentation')
    mgdm.setAdjustIntensityPriors(adjust_intensity_priors)
    mgdm.setComputePosterior(compute_posterior)
    mgdm.setDiffuseProbabilities(diffuse_probabilities)
    mgdm.setSteps(n_steps)
    mgdm.setTopology(topology)

    # load contrast image 1 and use it to set dimensions and resolution
    img = load_volume(contrast_image1)
    data = img.get_data()
    affine = img.get_affine()
    header = img.get_header()
    resolution = [x.item() for x in header.get_zooms()]
    dimensions = data.shape

    mgdm.setDimensions(dimensions[0], dimensions[1], dimensions[2])
    mgdm.setResolutions(resolution[0], resolution[1], resolution[2])

    # convert orientation information to mgdm slice and orientation info
    sliceorder, LR, AP, IS = _get_mgdm_orientation(affine, mgdm)
    mgdm.setOrientations(sliceorder, LR, AP, IS)

    # input image 1
    mgdm.setContrastImage1(cbstools.JArray('float')(
                                            (data.flatten('F')).astype(float)))
    mgdm.setContrastType1(contrast_type1)

    # if further contrast are specified, input them
    if contrast_image2 is not None:
        data = load_volume(contrast_image2[idx]).get_data()
        mgdm.setContrastImage2(cbstools.JArray('float')(
                                            (data.flatten('F')).astype(float)))
        mgdm.setContrastType2(contrast_type2)

        if contrast_image3 is not None:
            data = load_volume(contrast_image3[idx]).get_data()
            mgdm.setContrastImage3(cbstools.JArray('float')(
                                            (data.flatten('F')).astype(float)))
            mgdm.setContrastType3(contrast_type3)

            if contrast_image4 is not None:
                data = load_volume(contrast_image4[idx]).get_data()
                mgdm.setContrastImage4(cbstools.JArray('float')(
                                            (data.flatten('F')).astype(float)))
                mgdm.setContrastType4(contrast_type4)

    # execute MGDM
    try:
        print("Executing MGDM on your inputs")
        mgdm.execute()

    except:
        # if the Java module fails, reraise the error it throws
        print("\n The underlying Java code did not execute cleanly: ")
        print sys.exc_info()[0]
        raise
        return

    # reshape output to what nibabel likes
    seg_data = np.reshape(np.array(mgdm.getSegmentedBrainImage(),
                                   dtype=np.int32), dimensions, 'F')
    lbl_data = np.reshape(np.array(mgdm.getPosteriorMaximumLabels4D(),
                                   dtype=np.int32), dimensions, 'F')
    mems_data = np.reshape(np.array(mgdm.getPosteriorMaximumMemberships4D(),
                                    dtype=np.float32), dimensions, 'F')
    dist_data = np.reshape(np.array(mgdm.getLevelsetBoundaryImage(),
                                    dtype=np.float32), dimensions, 'F')

    # adapt header max for each image so that correct max is displayed
    # and create nifiti objects
    header['cal_max'] = np.max(seg_data)
    seg = nb.Nifti1Image(seg_data, affine, header)

    header['cal_max'] = np.max(lbl_data)
    lbls = nb.Nifti1Image(lbl_data, affine, header)

    header['cal_max'] = np.max(mems_data)
    mems = nb.Nifti1Image(mems_data, affine, header)

    header['cal_max'] = np.max(dist_data)
    dist = nb.Nifti1Image(dist_data, affine, header)

    if save_data:
        output_dir = _output_dir_4saving(output_dir, contrast_image1)
        print("\n Saving outputs to {0}".format(output_dir))

        # TODO fix the suffixes
        seg_file = _fname_4saving(rootfile=contrast_image1,
                                  suffix='mgdm_seg', base_name=file_name,
                                  extension=file_extension)

        lbl_file = _fname_4saving(rootfile=contrast_image1,
                                  suffix='mgmd_lbls', base_name=file_name,
                                  extension=file_extension)

        mems_file = _fname_4saving(rootfile=contrast_image1,
                                   suffix='mgdm_mems', base_name=file_name,
                                   extension=file_extension)

        dist_file = _fname_4saving(rootfile=contrast_image1,
                                   suffix='mgdm_dist', base_name=file_name,
                                   extension=file_extension)

        save_volume(os.path.join(output_dir, seg_file), seg)
        save_volume(os.path.join(output_dir, lbl_file), lbls)
        save_volume(os.path.join(output_dir, mems_file), mems)
        save_volume(os.path.join(output_dir, levels_file), levels)

    return dict{'segmentation': seg, 'labels': lbls,
                'memberships': mems, 'distance': dist}
