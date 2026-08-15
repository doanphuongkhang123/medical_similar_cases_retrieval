# Third-party source record

These shallow clones are pinned for source review and reproducibility. They are
not part of the project's own implementation and their licenses are preserved
inside their respective directories.

| Repository | Commit | Role in this workspace | License |
|---|---|---|---|
| `healthylaife/GT-BEHRT` | `d3d8384e0bea485095050ddafd5eb85e8db4c1f1` | Reference for visit token, NAM and MNP; no upstream license, so no source is copied. | none supplied |
| `Nadkarni-Lab/InfEHR` | `4b4fee76a67bd43388ad42c563688f60e65dfeb1` | Apache-2.0 reference for the VICReg/MI objective; adapted to typed sparse visit graphs. | Apache-2.0 |
| `xiaoxiang0605/AID-MAE` | `0b5995efa6b775b3d867dadce34926bcb8a947e1` | MIT reference for intrinsic-versus-augmented numeric masking. | MIT |
| `zzachw/MUSE` | `cdec2aceff40bad0679df2dc2716cdc13e8ae315` | Deferred until clinical-note/modality stage. Do not run its Neptune `--official_run` mode. | MIT |
| `HoytWen/GCVR` | `de2673f09de56db436626800f707c82a9c47dd27` | Deferred optional reconstruction reference; no source is copied. | none supplied |

The code in `src/rfssl` does not use labels, clinical note text, PDF, or image
data. It never logs or writes free-text EHR values.

