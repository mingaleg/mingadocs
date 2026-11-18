# mingadocs

A home-brewed Django app for paper documents: it prints Archive Serial Number
(ARN) barcode labels, scans labelled pages through SANE, reads the barcodes
back, and files the pages as numbered document PDFs.

See [`docs/README.md`](docs/README.md) for the overview, development setup and
deployment (it is a Nix flake with a NixOS module).
