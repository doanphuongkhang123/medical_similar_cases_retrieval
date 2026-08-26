# Third-party source record

These shallow clones are pinned for source review and reproducibility. They are
not part of the project's own implementation and their licenses are preserved
inside their respective directories.

| Repository | Commit | Role in this workspace | License |
|---|---|---|---|
| `healthylaife/GT-BEHRT` | `d3d8384e0bea485095050ddafd5eb85e8db4c1f1` | Reference for visit token, NAM and MNP; no upstream license, so no source is copied. | none supplied |
| `Nadkarni-Lab/InfEHR` | `4b4fee76a67bd43388ad42c563688f60e65dfeb1` | Apache-2.0 reference for the VICReg/MI objective; adapted to typed sparse visit graphs. | Apache-2.0 |
| `xiaoxiang0605/AID-MAE` | `0b5995efa6b775b3d867dadce34926bcb8a947e1` | MIT reference for intrinsic-versus-augmented numeric masking. | MIT |

The code in `src/ehr_graph_ssl` does not use labels, clinical note text, PDF,
or image data. It never logs or writes free-text EHR values.
