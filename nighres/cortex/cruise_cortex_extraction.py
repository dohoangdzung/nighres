import numpy as np
import nibabel as nb
import os
import sys
import nighresjava
from ..io import load_volume, save_volume, time_log
from ..utils import _output_dir_4saving, _fname_4saving, \
                    _check_topology_lut_dir, _check_atlas_file, \
                    _check_available_memory
import time

def cruise_cortex_extraction(init_image, wm_image, gm_image, csf_image,
                             vd_image=None, data_weight=0.4,
                             regularization_weight=0.1,
                             max_iterations=500, normalize_probabilities=False,
                             correct_wm_pv=True, wm_dropoff_dist=1.0,
                             topology='wcs', topology_lut_dir=None,
                             save_data=False, overwrite=False, output_dir=None,
                             file_name=None, log_file="timelog.json"):
    """ CRUISE cortex extraction

    Segments the cortex from a whole brain segmented data set with the CRUISE
    method (includes customized partial voluming corrections and the
    Anatomically-Consistent Enhancement (ACE) of sulcal fundi).

    Note that the main input images are generated by the nighres module
    :func:`nighres.brain.extract_brain_region`.

    Parameters
    ----------
    init_image: niimg
        Initial white matter (WM) segmentation mask (binary mask>0 inside WM)
    wm_image: niimg
        Filled WM probability map (values in [0,1], including subcortical GM
        and ventricles)
    gm_image: niimg
        Cortical gray matter (GM) probability map (values in [0,1], highest
        inside the cortex)
    csf_image: niimg
        Sulcal cerebro-spinal fluid (CSf) and background probability map
        (values in [0,1], highest in CSf and masked regions)
    vd_image: niimg, optional
        Additional probability map of vessels and dura mater to be excluded
    data_weight: float
        Weighting of probability-based balloon forces in CRUISE (default 0.4,
        sum of {data_weight,regularization_weight} should be below or equal
        to 1)
    regularization_weight: float
        Weighting of curvature regularization forces in CRUISE (default 0.1,
        sum of {data_weight,regularization_weight} should be below or equal
        to 1)
    max_iterations: int
        Maximum number of iterations in CRUISE (default is 500)
    normalize_probabilities: bool
        Whether to normalize the wm, gm, and csf probabilities
        (default is False)
    correct_wm_pv: bool
        Whether to correct for WM partial voluming in gyral crowns
        (default is True)
    wm_dropoff_dist: float
        Distance parameter to lower WM probabilities away from current
        segmentation (default is 1.0 voxel)
    topology: {'wcs', 'no'}
        Topology setting, choose 'wcs' (well-composed surfaces) for strongest
        topology constraint, 'no' for no topology constraint (default is 'wcs')
    topology_lut_dir: str
        Path to directory in which topology files are stored (default is stored
        in TOPOLOGY_LUT_DIR)
    save_data: bool
        Save output data to file (default is False)
    overwrite: bool
        Overwrite existing results (default is False)
    output_dir: str, optional
        Path to desired output directory, will be created if it doesn't exist
    file_name: str, optional
        Desired base name for output files with file extension
        (suffixes will be added)

    Returns
    ----------
    dict
        Dictionary collecting outputs under the following keys
        (suffix of output files in brackets)

        * cortex (niimg): Hard segmentation of the cortex with labels
          background=0, gm=1, and wm=2 (_cruise_cortex)
        * gwb (niimg): Gray-White matter Boundary (GWB) level set function
          (_cruise_gwb)
        * cgb (niimg): CSF-Gray matter Boundary (CGB) level set function
          (_cruise_cgb)
        * avg (niimg): Central level set function, obtained as geometric
          average of GWB and CGB (*not* the middle depth of the
          cortex, use volumetric_layering if you want accurate
          depth measures) (_cruise-avg)
        * thickness (niimg): Simple cortical thickness estimate: distance to
          the GWB and CGB surfaces, in mm (_cruise-thick)
        * pwm (niimg): Optimized WM probability, including partial volume and
          distant values correction (_cruise-pwm)
        * pgm (niimg): Optimized GM probability, including CSF sulcal ridges
          correction (_cruise_pgm)
        * pcsf (niimg): Optimized CSF probability, including sulcal ridges and
          vessel/dura correction (_cruise-pwm)

    Notes
    ----------
    Original algorithm by Xiao Han. Java module by Pierre-Louis Bazin.
    Algorithm details can be found in [1]_

    References
    ----------
    .. [1] X. Han, D.L. Pham, D. Tosun, M.E. Rettmann, C. Xu, and J. L. Prince,
       CRUISE: Cortical Reconstruction Using Implicit Surface Evolution,
       NeuroImage, vol. 23, pp. 997--1012, 2004
    """

    print('\nCRUISE Cortical Extraction')
    start = time.time()

    # check topology_lut_dir and set default if not given
    topology_lut_dir = _check_topology_lut_dir(topology_lut_dir)

    # make sure that saving related parameters are correct
    if save_data:
        output_dir = _output_dir_4saving(output_dir, gm_image)

        cortex_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                     rootfile=gm_image,
                                     suffix='cruise-cortex', ))

        gwb_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                  rootfile=gm_image,
                                  suffix='cruise-gwb', ))

        cgb_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                  rootfile=gm_image,
                                  suffix='cruise-cgb', ))

        avg_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                  rootfile=gm_image,
                                  suffix='cruise-avg', ))

        thick_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                    rootfile=gm_image,
                                    suffix='cruise-thick', ))

        pwm_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                  rootfile=gm_image,
                                  suffix='cruise-pwm', ))

        pgm_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                  rootfile=gm_image,
                                  suffix='cruise-pgm', ))

        pcsf_file = os.path.join(output_dir,
                        _fname_4saving(module=__name__,file_name=file_name,
                                   rootfile=gm_image,
                                   suffix='cruise-pcsf', ))
        if overwrite is False \
            and os.path.isfile(cortex_file) \
            and os.path.isfile(gwb_file) \
            and os.path.isfile(cgb_file) \
            and os.path.isfile(avg_file) \
            and os.path.isfile(thick_file) \
            and os.path.isfile(pwm_file) \
            and os.path.isfile(pgm_file) \
            and os.path.isfile(pcsf_file) :

            print("skip computation (use existing results)")
            output = {'cortex': cortex_file,
                      'gwb': gwb_file,
                      'cgb': cgb_file,
                      'avg': avg_file,
                      'thickness': thick_file,
                      'pwm': pwm_file,
                      'pgm': pgm_file,
                      'pcsf': pcsf_file}
            return output

    # start virtual machine, if not already running
    try:
        mem = _check_available_memory()
        nighresjava.initVM(initialheap=mem['init'], maxheap=mem['max'])
    except ValueError:
        pass
    # create instance
    cruise = nighresjava.CortexOptimCRUISE()

    # set parameters
    cruise.setDataWeight(data_weight)
    cruise.setRegularizationWeight(regularization_weight)
    cruise.setMaxIterations(max_iterations)
    cruise.setNormalizeProbabilities(normalize_probabilities)
    cruise.setCorrectForWMGMpartialVoluming(correct_wm_pv)
    cruise.setWMdropoffDistance(wm_dropoff_dist)
    cruise.setTopology(topology)
    cruise.setTopologyLUTdirectory(topology_lut_dir)

    # load images
    init = load_volume(init_image, log_file=log_file)
    init_data = init.get_data()
    affine = init.affine
    header = init.header
    resolution = [x.item() for x in header.get_zooms()]
    dimensions = init_data.shape
    cruise.setDimensions(dimensions[0], dimensions[1], dimensions[2])
    cruise.setResolutions(resolution[0], resolution[1], resolution[2])
    cruise.importInitialWMSegmentationImage(nighresjava.JArray('int')(
                                (init_data.flatten('F')).astype(int).tolist()))

    wm_data = load_volume(wm_image, log_file=log_file).get_data()
    cruise.setFilledWMProbabilityImage(nighresjava.JArray('float')(
                                        (wm_data.flatten('F')).astype(float)))

    gm_data = load_volume(gm_image, log_file=log_file).get_data()
    cruise.setGMProbabilityImage(nighresjava.JArray('float')(
                                        (gm_data.flatten('F')).astype(float)))

    csf_data = load_volume(csf_image, log_file=log_file).get_data()
    cruise.setCSFandBGProbabilityImage(nighresjava.JArray('float')(
                                        (csf_data.flatten('F')).astype(float)))

    if vd_image is not None:
        vd_data = load_volume(vd_image, log_file=log_file).get_data()
        cruise.setVeinsAndDuraProbabilityImage(nighresjava.JArray('float')(
                                        (vd_data.flatten('F')).astype(float)))

    # execute
    try:
        cruise.execute()

    except:
        # if the Java module fails, reraise the error it throws
        print("\n The underlying Java code did not execute cleanly: ")
        print(sys.exc_info()[0])
        raise
        return

    # reshape output to what nibabel likes
    cortex_data = np.reshape(np.array(cruise.getCortexMask(),
                                      dtype=np.int32), dimensions, 'F')
    gwb_data = np.reshape(np.array(cruise.getWMGMLevelset(),
                                   dtype=np.float32), dimensions, 'F')
    cgb_data = np.reshape(np.array(cruise.getGMCSFLevelset(),
                                   dtype=np.float32), dimensions, 'F')
    avg_data = np.reshape(np.array(cruise.getCentralLevelset(),
                                   dtype=np.float32), dimensions, 'F')
    thick_data = np.reshape(np.array(cruise.getCorticalThickness(),
                                     dtype=np.float32), dimensions, 'F')
    pwm_data = np.reshape(np.array(cruise.getCerebralWMprobability(),
                                   dtype=np.float32), dimensions, 'F')
    pgm_data = np.reshape(np.array(cruise.getCorticalGMprobability(),
                                   dtype=np.float32), dimensions, 'F')
    pcsf_data = np.reshape(np.array(cruise.getSulcalCSFprobability(),
                                    dtype=np.float32), dimensions, 'F')

    # adapt header min, max for each image so that correct max is displayed
    # and create nifiti objects
    header['cal_min'] = np.nanmax(cortex_data)
    header['cal_max'] = np.nanmax(cortex_data)
    cortex = nb.Nifti1Image(cortex_data, affine, header)

    header['cal_min'] = np.nanmax(gwb_data)
    header['cal_max'] = np.nanmax(gwb_data)
    gwb = nb.Nifti1Image(gwb_data, affine, header)

    header['cal_min'] = np.nanmax(cgb_data)
    header['cal_max'] = np.nanmax(cgb_data)
    cgb = nb.Nifti1Image(cgb_data, affine, header)

    header['cal_min'] = np.nanmax(avg_data)
    header['cal_max'] = np.nanmax(avg_data)
    avg = nb.Nifti1Image(avg_data, affine, header)

    header['cal_min'] = np.nanmax(thick_data)
    header['cal_max'] = np.nanmax(thick_data)
    thickness = nb.Nifti1Image(thick_data, affine, header)

    header['cal_min'] = np.nanmax(pwm_data)
    header['cal_max'] = np.nanmax(pwm_data)
    pwm = nb.Nifti1Image(pwm_data, affine, header)

    header['cal_min'] = np.nanmax(pgm_data)
    header['cal_max'] = np.nanmax(pgm_data)
    pgm = nb.Nifti1Image(pgm_data, affine, header)

    header['cal_min'] = np.nanmax(pcsf_data)
    header['cal_max'] = np.nanmax(pcsf_data)
    pcsf = nb.Nifti1Image(pcsf_data, affine, header)

    if save_data:
        save_volume(cortex_file, cortex, log_file=log_file)
        save_volume(gwb_file, gwb, log_file=log_file)
        save_volume(cgb_file, cgb, log_file=log_file)
        save_volume(avg_file, avg, log_file=log_file)
        save_volume(thick_file, thickness, log_file=log_file)
        save_volume(pwm_file, pwm, log_file=log_file)
        save_volume(pgm_file, pgm, log_file=log_file)
        save_volume(pcsf_file, pcsf, log_file=log_file)

        result = {'cortex': cortex_file, 'gwb': gwb_file, 'cgb': cgb_file, 'avg': avg_file,
                'thickness': thick_file, 'pwm': pwm_file, 'pgm': pgm_file, 'pcsf': pcsf_file}
    else:
        result = {'cortex': cortex, 'gwb': gwb, 'cgb': cgb, 'avg': avg,
                'thickness': thickness, 'pwm': pwm, 'pgm': pgm, 'pcsf': pcsf}

    end = time.time()
    time_log(log_file, "cruise_cortex_extraction", "makespan", None, start, end)

    return result
