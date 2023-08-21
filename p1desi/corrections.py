import pickle, os, fitsio, glob
import numpy as np
from functools import partial
from p1desi import metals, utils, hcd
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from matplotlib import cm


###################################################
############## Creating corrections ###############
###################################################


def plot_and_compute_ratio_power(
    pk,
    pk2,
    path_out,
    name_correction,
    suffix,
    model,
    zmax,
    kmin_AA,
    kmin_fit_AA,
    kmax_AA,
    model_param=None,
    **plt_args,
):
    """
    plot_and_compute_ratio_power - Plot the ratio of two power spectra and fit a curve to the data

    Inputs:

        pk: object containing the power spectrum data to plot, with attributes k, norm_p, and norm_err for the wave number k, power spectrum P, and error on P respectively
        pk2: object containing the power spectrum data to divide pk by, with attributes k, norm_p, and norm_err for the wave number k, power spectrum P, and error on P respectively
        path_out: string specifying the filepath to save the plot
        name_correction: string specifying the correction applied to the power spectra
        suffix: string to add to the end of the plot file name
        model: string specifying the type of curve to fit to the data, either "poly" for a polynomial or "rogers" for a function defined in Rogers et al. (2020)
        zmax: maximum redshift to plot
        kmin_AA: minimum wave number in inverse Angstroms to plot
        kmin_fit_AA: minimum wave number in inverse Angstroms to use for fitting the curve
        kmax_AA: maximum wave number in inverse Angstroms to plot
        model_param: dictionary of parameters for the fitting function, required if model is "poly" and should contain the key "order_poly" specifying the order of the polynomial
        **plt_args: additional arguments to be passed to the plot, including:
            dk: shift in wave number between redshift bins
            zseparation: redshift at which to split the plot into two subplots
            ymin: minimum y value for the plot
            ymax: maximum y value for the plot
            ylabel: string for the y-axis label

    Outputs:

        fig: figure object for the plot
        ax: axis object for the plot
        params: list of arrays of fitted curve parameters for each redshift
    """

    dk = utils.return_key(plt_args, "dk", 0.0)
    zseparation = utils.return_key(plt_args, "zseparation", 2.9)
    ymin = utils.return_key(plt_args, "ymin", 0.95)
    ymax = utils.return_key(plt_args, "ymax", 1.05)
    ylabel = utils.return_key(plt_args, "ylabel", r"$A_{\mathrm{corr}}$")
    marker_style = utils.return_key(plt_args, "marker_style", ".")
    marker_size = utils.return_key(plt_args, "marker_size", 7)
    fontsize = utils.return_key(plt_args, "fontsize", 21)
    fontsize_y = utils.return_key(plt_args, "fontsize_y", 21)
    fontlegend = utils.return_key(plt_args, "fontlegend", 18)
    fontticks = utils.return_key(plt_args, "fontticks", 19)
    color_map = utils.return_key(plt_args, "color_map", "default")
    if color_map == "default":
        colors = [f"C{i}" for i, z in enumerate(pk.zbin) if z < zmax]
    elif color_map == "rainbow":
        colors = cm.rainbow(np.linspace(0, 1, len(pk.zbin[pk.zbin < zmax])))
    elif color_map == "jet":
        colors = cm.jet(np.linspace(0, 1, len(pk.zbin[pk.zbin < zmax])))

    params = []

    fig, ax = plt.subplots(2, 1, figsize=(8, 8), sharex=True)

    z_arr, k_arr, ratio_arr, err_arr = [], [], [], []
    for i, z in enumerate(pk.zbin):
        if z < zseparation:
            axplt = ax[0]
        else:
            axplt = ax[1]
        if z < zmax:
            if pk.velunits:
                kmax = float(utils.kAAtokskm(kmax_AA, z=z))
                kmin = float(utils.kAAtokskm(kmin_AA, z=z))
                kmin_fit = float(utils.kAAtokskm(kmin_fit_AA, z=z))
            else:
                kmax = kmax_AA
                kmin = kmin_AA
                kmin_fit = kmin_fit_AA
            k = pk.k[z]

            norm_pk2_interp = interp1d(
                pk2.k[z],
                pk2.norm_p[z],
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate",
            )(k)
            norm_err_pk2_interp = interp1d(
                pk2.k[z],
                pk2.norm_err[z],
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate",
            )(k)

            ratio = pk.norm_p[z] / norm_pk2_interp
            err_ratio = (pk.norm_p[z] / norm_pk2_interp) * np.sqrt(
                (pk.norm_err[z] / pk.norm_p[z]) ** 2
                + (norm_err_pk2_interp / norm_pk2_interp) ** 2
            )

            mask = (
                np.isnan(k)
                | np.isnan(ratio)
                | np.isnan(err_ratio)
                | (k > kmax)
                | (k < kmin)
            )
            k = k[~mask]
            ratio = ratio[~mask]
            err_ratio = err_ratio[~mask]

            axplt.errorbar(
                k + i * dk,
                ratio,
                yerr=err_ratio,
                marker=marker_style,
                color=colors[i],
                markersize=marker_size,
                linestyle="None",
                label=r"$z = ${:1.1f}".format(z),
            )
            z_arr.append([z for i in range(len(k))])
            k_arr.append(k)
            ratio_arr.append(ratio)
            err_arr.append(err_ratio)

            mask_fit = k > kmin_fit

            if model == "poly":
                weights = 1 / err_ratio
                p = np.polyfit(
                    k[mask_fit],
                    ratio[mask_fit],
                    model_param["order_poly"],
                    w=weights[mask_fit],
                )
                k_th = np.linspace(np.min(k), np.max(k), 2000)
                axplt.plot(k_th, np.poly1d(p)(k_th), color=colors[i], ls="--")
                params.append(p)

            elif model == "power":
                popt, pcov = curve_fit(
                    model_residual_correction,
                    xdata=k,
                    ydata=ratio,
                    sigma=err_ratio,
                    p0=[1.0, 0.0, 0.0],
                    bounds=(
                        [-np.inf, -5, 0],
                        [np.inf, 5, 5],
                    ),
                )
                k_th = np.linspace(np.min(k), np.max(k), 2000)
                axplt.plot(
                    k_th,
                    model_residual_correction(k_th, *popt),
                    color=colors[i],
                    ls="--",
                )
                params.append(popt)

            elif model == "rogers":
                func = partial(hcd.rogers, z)
                if pk.velunits:
                    b0_rogers = 429.58
                else:
                    b0_rogers = 7.316
                popt, pcov = curve_fit(
                    func,
                    xdata=k,
                    ydata=ratio,
                    sigma=err_ratio,
                    p0=[0.8633, 0.2943, b0_rogers, -0.4964, 1.0, 0.01],
                    bounds=(
                        [0, 0, 0, -np.inf, 0, 0],
                        [np.inf, np.inf, np.inf, 0, np.inf, np.inf],
                    ),
                )
                k_th = np.linspace(np.min(k), np.max(k), 2000)
                axplt.plot(k_th, func(k_th, *popt), color=f"C{i}")
                params.append(popt)

    z_arr, k_arr, ratio_arr, err_arr = (
        np.concatenate(z_arr),
        np.concatenate(k_arr),
        np.concatenate(ratio_arr),
        np.concatenate(err_arr),
    )

    if pk.velunits:
        ax[1].set_xlabel(
            r"$k~[\mathrm{s}$" + r"$\cdot$" + "$\mathrm{km}^{-1}]$", fontsize=fontsize
        )
    else:
        ax[1].set_xlabel(r"$k~[\mathrm{\AA}^{-1}]$", fontsize=fontsize)
    ax[0].set_ylabel(ylabel, fontsize=fontsize_y)
    ax[1].set_ylabel(ylabel, fontsize=fontsize_y)
    ax[0].xaxis.set_tick_params(labelsize=fontticks)
    ax[0].yaxis.set_tick_params(labelsize=fontticks)
    ax[1].xaxis.set_tick_params(labelsize=fontticks)
    ax[1].yaxis.set_tick_params(labelsize=fontticks)
    ax[0].legend(ncol=2, fontsize=fontlegend)
    ax[1].legend(ncol=2, fontsize=fontlegend)
    ax[0].set_ylim(ymin, ymax)
    ax[1].set_ylim(ymin, ymax)
    ax[0].margins(x=0)
    fig.tight_layout()

    if pk.velunits:
        fig.savefig(os.path.join(path_out, f"{name_correction}_{suffix}_kms.pdf"))
        fig.savefig(os.path.join(path_out, f"{name_correction}_{suffix}_kms.png"))
        pickle.dump(
            params,
            open(
                os.path.join(path_out, f"{name_correction}_{suffix}_kms.pickle"), "wb"
            ),
        )
        np.savetxt(
            os.path.join(path_out, f"{name_correction}_{suffix}_kms.txt"),
            np.transpose(np.stack([z_arr, k_arr, ratio_arr, err_arr])),
            header="REDSHIFT & WAVENUMBER [s.km^-1] & RATIO POWER SPECTRA & ERROR RATIO",
        )
    else:
        fig.savefig(os.path.join(path_out, f"{name_correction}_{suffix}.pdf"))
        fig.savefig(os.path.join(path_out, f"{name_correction}_{suffix}.png"))
        pickle.dump(
            params,
            open(os.path.join(path_out, f"{name_correction}_{suffix}.pickle"), "wb"),
        )
        np.savetxt(
            os.path.join(path_out, f"{name_correction}_{suffix}.txt"),
            np.transpose(np.stack([z_arr, k_arr, ratio_arr, err_arr])),
            header="REDSHIFT & WAVENUMBER [Ang^-1] & RATIO POWER SPECTRA & ERROR RATIO",
        )


def plot_and_compute_average_ratio_power(
    pk,
    pk2,
    path_out,
    name_correction,
    suffix,
    zmax,
    kmin_AA,
    kmax_AA,
    **plt_args,
):
    k_tot, ratio_tot, err_tot = [], [], []
    labelsize = utils.return_key(plt_args, "labelsize", 18)
    fontsize_x = utils.return_key(plt_args, "fontsize_x", 21)
    fontsize_y = utils.return_key(plt_args, "fontsize_y", 22)
    ymin = utils.return_key(plt_args, "ymin", 0.9)
    ymax = utils.return_key(plt_args, "ymax", 1.02)

    plt.figure(figsize=(8, 5))

    for z in pk.zbin[1:]:
        if z < zmax:
            if pk.velunits:
                kmax = float(utils.kAAtokskm(kmax_AA, z=z))
                kmin = float(utils.kAAtokskm(kmin_AA, z=z))
            else:
                kmax = kmax_AA
                kmin = kmin_AA

            k = pk.k[z]
            ratio = pk.norm_p[z] / pk2.norm_p[z]
            err_ratio = (pk.norm_p[z] / pk2.norm_p[z]) * np.sqrt(
                (pk.norm_err[z] / pk.norm_p[z]) ** 2
                + (pk2.norm_err[z] / pk2.norm_p[z]) ** 2
            )
            mask = (
                np.isnan(k)
                | np.isnan(ratio)
                | np.isnan(err_ratio)
                | (k > kmax)
                | (k < kmin)
            )

            k[mask] = np.nan
            ratio[mask] = np.nan
            err_ratio[mask] = np.nan

            plt.plot(k, ratio, alpha=0.5, ls=":", color=f"k")

            k_tot.append(k)
            ratio_tot.append(ratio)
            err_tot.append(err_ratio)

    k_tot = np.nanmean(k_tot, axis=0)
    ratio_tot = np.nanmean(ratio_tot, axis=0)
    err_tot = np.nanmean(err_tot, axis=0)
    mask = np.isnan(k_tot) | np.isnan(ratio_tot) | np.isnan(err_tot)
    k_tot = k_tot[~mask]
    ratio_tot = ratio_tot[~mask]
    err_tot = err_tot[~mask]

    plt.errorbar(
        k_tot, ratio_tot, err_tot, marker=".", markersize=10, ls="None", color="C0"
    )

    func = lambda k, a, b, c: a * k**2 + b * k + c
    param = curve_fit(func, k_tot, ratio_tot, sigma=err_tot, p0=[0, 0, 0])[0]
    k = np.linspace(np.min(k_tot), np.max(k_tot), 1000)
    plt.plot(k, np.poly1d(param)(k))

    plt.ylabel(
        r"$\langle P_{1\mathrm{D},\alpha,\mathrm{RAW}} / P_{1\mathrm{D},\alpha,\mathrm{CCD}} \rangle_z$",
        fontsize=fontsize_y,
    )
    if pk.velunits:
        plt.xlabel(
            r"$k~[\mathrm{s}$" + r"$\cdot$" + "$\mathrm{km}^{-1}]$", fontsize=fontsize_x
        )
    else:
        plt.xlabel(r"$k~[\mathrm{\AA}^{-1}]$", fontsize=fontsize_x)
    plt.ylim(ymin, ymax, 1.02)

    plt.gca().xaxis.set_tick_params(labelsize=labelsize)
    plt.gca().yaxis.set_tick_params(labelsize=labelsize)
    plt.tight_layout()

    if pk.velunits:
        plt.savefig(os.path.join(path_out, f"{name_correction}_{suffix}_kms.pdf"))
        plt.savefig(os.path.join(path_out, f"{name_correction}_{suffix}_kms.png"))
        pickle.dump(
            param,
            open(
                os.path.join(path_out, f"{name_correction}_{suffix}_kms.pickle"), "wb"
            ),
        )
        np.savetxt(
            os.path.join(path_out, f"{name_correction}_{suffix}_kms.txt"),
            np.transpose(np.stack([k_tot, ratio_tot, err_tot])),
            header="WAVENUMBER [s.km^-1] & MEAN POWER SPECTRUM RATIO & ERROR RATIO",
        )
    else:
        plt.savefig(os.path.join(path_out, f"{name_correction}_{suffix}.pdf"))
        plt.savefig(os.path.join(path_out, f"{name_correction}_{suffix}.png"))
        pickle.dump(
            param,
            open(os.path.join(path_out, f"{name_correction}_{suffix}.pickle"), "wb"),
        )
        np.savetxt(
            os.path.join(path_out, f"{name_correction}_{suffix}.txt"),
            np.transpose(np.stack([k_tot, ratio_tot, err_tot])),
            header="WAVENUMBER [Ang^-1] & MEAN POWER SPECTRUM RATIO & ERROR RATIO",
        )


###################################################
############## Applying corrections ###############
###################################################


######### Corrections masking + continuum #########


def prepare_hcd_correction(zbins, file_correction_hcd):
    param_hcd = pickle.load(open(file_correction_hcd, "rb"))
    A_hcd = {}
    for iz, z in enumerate(zbins):
        if iz >= len(param_hcd):
            print(f"Redshift bin {z} have no hcd correction")
            A_hcd[z] = np.poly1d(1)
        else:
            A_hcd[z] = np.poly1d(param_hcd[iz])
    return A_hcd


def prepare_lines_correction(zbins, file_correction_lines):
    param_lines = pickle.load(open(file_correction_lines, "rb"))
    A_lines = {}
    for iz, z in enumerate(zbins):
        if iz >= len(param_lines):
            print(f"Redshift bin {z} have no line correction")
            A_lines[z] = np.poly1d(1)
        else:
            A_lines[z] = np.poly1d(param_lines[iz])
    return A_lines


def prepare_cont_correction(zbins, file_correction_cont):
    param_cont = pickle.load(open(file_correction_cont, "rb"))
    A_cont = {}
    for iz, z in enumerate(zbins):
        if iz >= len(param_cont):
            print(f"Redshift bin {z} have no continuum correction")
            A_cont[z] = np.poly1d(1)
        else:
            A_cont[z] = np.poly1d(param_cont[iz])
    return A_cont


def prepare_resolution_correction(zbins, file_correction_resolution):
    param_cont = pickle.load(open(file_correction_resolution, "rb"))
    A_resolution = {}
    for _, z in enumerate(zbins):
        A_resolution[z] = np.poly1d(param_cont)
    return A_resolution


def apply_correction(pk, zmax, file_correction, type_correction):
    zbins = pk.zbin[pk.zbin < zmax]
    A_corr = eval(f"prepare_{type_correction}_correction")(zbins, file_correction)
    for z in zbins:
        pk.p[z] = pk.p[z] * A_corr[z](pk.k[z])
        pk.norm_p[z] = pk.norm_p[z] * A_corr[z](pk.k[z])
        pk.err[z] = pk.err[z] * A_corr[z](pk.k[z])
        pk.norm_err[z] = pk.norm_err[z] * A_corr[z](pk.k[z])


def prepare_hcd_correction_eboss(zbins, hcd_eboss_name):
    param_hcd_eboss = np.loadtxt(hcd_eboss_name)
    A_hcd = {}
    for iz, z in enumerate(zbins):
        A_hcd[z] = np.poly1d(param_hcd_eboss[iz])
    return A_hcd


def prepare_lines_correction_eboss(zbins, lines_eboss_name):
    param_lines_eboss = np.loadtxt(lines_eboss_name)
    A_lines = {}
    for iz, z in enumerate(zbins):
        A_lines[z] = np.poly1d(param_lines_eboss[iz])
    return A_lines


def model_cont_correction_eboss(a0, a1, k):
    return (a0 / k) + a1


def prepare_cont_correction_eboss(zbins, cont_eboss_name):
    param_cont_eboss = np.loadtxt(cont_eboss_name)
    A_cont = {}
    for iz, z in enumerate(zbins):
        if iz < 6:
            A_cont[z] = partial(
                model_cont_correction_eboss,
                param_cont_eboss[iz][0],
                param_cont_eboss[iz][1],
            )
        else:
            A_cont[z] = np.poly1d(param_cont_eboss[iz])
    return A_cont


def apply_correction_eboss(pk, zmax, file_correction, type_correction):
    zbins = pk.zbin[pk.zbin < zmax]
    A_corr = eval(f"prepare_{type_correction}_correction_eboss")(zbins, file_correction)
    for z in zbins:
        pk.p[z] = pk.p[z] / A_corr[z](pk.k[z])
        pk.norm_p[z] = pk.norm_p[z] / A_corr[z](pk.k[z])
        pk.err[z] = pk.err[z] / A_corr[z](pk.k[z])
        pk.norm_err[z] = pk.norm_err[z] / A_corr[z](pk.k[z])


############## Side band corrections ##############


def prepare_metal_subtraction(zbins, file_metal, velunits=False):
    (param_SB1_mean, param_SB1_indiv) = pickle.load(open(file_metal, "rb"))
    P_metal_m = {}
    for iz, z in enumerate(zbins):
        if velunits:
            P_metal_m[z] = partial(
                metals.model_SB1_indiv_kms,
                param_SB1_mean,
                param_SB1_indiv[iz][0],
                param_SB1_indiv[iz][1],
            )
        else:
            P_metal_m[z] = partial(
                metals.model_SB1_indiv,
                param_SB1_mean,
                z,
                param_SB1_indiv[iz][0],
                param_SB1_indiv[iz][1],
            )
    return P_metal_m


def subtract_metal(pk, zmax, file_metal):
    zbins = pk.zbin[pk.zbin < zmax]
    P_metal_m = prepare_metal_subtraction(zbins, file_metal, velunits=pk.velunits)
    for z in zbins:
        pk.p[z] = pk.p[z] - P_metal_m[z](pk.k[z])
        pk.norm_p[z] = pk.norm_p[z] - (pk.k[z] * P_metal_m[z](pk.k[z]) / np.pi)


def prepare_metal_correction_eboss(file_metal_eboss):
    param_sb_eboss = np.loadtxt(file_metal_eboss)
    return param_sb_eboss


def subtract_metal_eboss(pk, zmax, file_metal_eboss):
    zbins = pk.zbin[pk.zbin < zmax]
    param_sb_eboss = prepare_metal_correction_eboss(file_metal_eboss)
    nbin_eboss = 35
    klimInf_eboss = 0.000813
    klimSup_eboss = klimInf_eboss + nbin_eboss * 0.000542

    for z in zbins:
        mask_sb = param_sb_eboss[:, 0] == z
        k_sb_eboss = param_sb_eboss[:, 1][mask_sb]
        sb_eboss = param_sb_eboss[:, 2][mask_sb]

        deltak_eboss = (klimSup_eboss - klimInf_eboss) / nbin_eboss
        ib_eboss = ((k_sb_eboss - klimInf_eboss) / deltak_eboss).astype(int)
        cor_sb = np.zeros(k_sb_eboss.shape)
        slope_eboss = np.zeros(k_sb_eboss.shape)

        mask_k_sb_1 = k_sb_eboss < klimInf_eboss
        slope_eboss[mask_k_sb_1] = (sb_eboss[1] - sb_eboss[0]) / deltak_eboss
        cor_sb[mask_k_sb_1] = sb_eboss[0] + slope_eboss[mask_k_sb_1] * (
            k_sb_eboss[mask_k_sb_1] - deltak_eboss / 2 - klimInf_eboss
        )

        mask_k_sb_2 = (ib_eboss < nbin_eboss - 1) & (~mask_k_sb_1)
        slope_eboss[mask_k_sb_2] = (
            sb_eboss[ib_eboss[mask_k_sb_2] + 1] - sb_eboss[ib_eboss[mask_k_sb_2]]
        ) / deltak_eboss
        cor_sb[mask_k_sb_2] = sb_eboss[ib_eboss[mask_k_sb_2]] + slope_eboss[
            mask_k_sb_2
        ] * (
            k_sb_eboss[mask_k_sb_2]
            - deltak_eboss / 2
            - (klimInf_eboss + ib_eboss[mask_k_sb_2] * deltak_eboss)
        )

        mask_k_sb_3 = (~mask_k_sb_2) & (~mask_k_sb_1)
        slope_eboss[mask_k_sb_3] = (sb_eboss[-1] - sb_eboss[-2]) / deltak_eboss
        cor_sb[mask_k_sb_3] = sb_eboss[-1] + slope_eboss[mask_k_sb_3] * (
            k_sb_eboss[mask_k_sb_3] - deltak_eboss / 2 - (klimSup_eboss - deltak_eboss)
        )

        pk.p[z] = pk.p[z] - cor_sb
        pk.norm_p[z] = pk.norm_p[z] - (pk.k[z] * cor_sb / np.pi)


################ Noise corrections ################


def model_noise_correction(SNR, A, g, B):
    power_law = A * SNR ** (-g) + B
    return power_law


################ Apply corrections ################


def correct_individual_pk_noise(pk_in, pk_out, qsocat, correction):
    os.makedirs(pk_out, exist_ok=True)
    pk_files = glob.glob(os.path.join(pk_in, "Pk1D-*"))

    qso_file = fitsio.FITS(qsocat)["QSO_CAT"]
    targetid_qso = qso_file["TARGETID"][:]
    survey_qso = qso_file["SURVEY"][:]
    for i in range(len(pk_files)):
        pk_out_name = pk_files[i].split("/")[-1]
        f_out = fitsio.FITS(os.path.join(pk_out, pk_out_name), "rw", clobber=True)
        f = fitsio.FITS(pk_files[i])
        for j in range(1, len(f)):
            header = dict(f[j].read_header())
            snr = header["MEANSNR"]
            id = header["LOS_ID"]
            survey_id = survey_qso[np.argwhere(targetid_qso == id)[0]][0]
            p_noise_miss = model_noise_correction(snr, *correction[survey_id])
            line = f[j].read()
            new_line = np.zeros(
                line.size,
                dtype=[
                    (line.dtype.names[i], line.dtype[i]) for i in range(len(line.dtype))
                ]
                + [("PK_NOISE_MISS", ">f8")],
            )
            for name in line.dtype.names:
                new_line[name] = line[name]
            new_line["PK_NOISE"] = new_line["PK_NOISE"] + p_noise_miss
            new_line["PK_NOISE_MISS"] = np.full(line.size, p_noise_miss)
            f_out.write(new_line, header=header, extname=str(id))


def apply_p1d_corections(
    pk,
    zmax,
    apply_DESI_maskcont_corr,
    apply_eBOSS_maskcont_corr,
    apply_DESI_sb_corr,
    apply_eBOSS_sb_corr,
    correction_to_apply,
    file_correction_hcd=None,
    file_correction_hcd_eboss=None,
    file_correction_lines=None,
    file_correction_lines_eboss=None,
    file_correction_cont=None,
    file_correction_cont_eboss=None,
    file_correction_resolution=None,
    file_metal=None,
    file_metal_eboss=None,
):
    if apply_DESI_maskcont_corr & apply_eBOSS_maskcont_corr:
        return KeyError("Same type of correction is applied two times")

    if apply_DESI_sb_corr & apply_eBOSS_sb_corr:
        return KeyError("Same type of correction is applied two times")

    if apply_DESI_maskcont_corr:
        for type_correction in correction_to_apply:
            apply_correction(
                pk, zmax, eval(f"file_correction_{type_correction}"), type_correction
            )

    if apply_eBOSS_maskcont_corr:
        for type_correction in correction_to_apply:
            apply_correction_eboss(
                pk,
                zmax,
                eval(f"file_correction_{type_correction}_eboss"),
                type_correction,
            )

    if apply_DESI_sb_corr:
        subtract_metal(pk, zmax, file_metal)

    if apply_eBOSS_sb_corr:
        subtract_metal_eboss(pk, zmax, file_metal_eboss)

    return pk
