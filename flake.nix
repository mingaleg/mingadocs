{
  description = "Scan, number and file paper documents, and print their ARN labels";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    # Django 6.1 / Python 3.14 and the newer zxing-cpp, pypdfium2 and reportlab
    # aren't in nixpkgs yet, so the Python side is built from uv.lock instead.
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
    }:
    let
      inherit (nixpkgs) lib;
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAll = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      pythonSetFor =
        pkgs:
        (pkgs.callPackage pyproject-nix.build.packages { python = pkgs.python314; }).overrideScope (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.wheel
            (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
            (import ./nix/python-overrides.nix { inherit pkgs; })
          ]
        );
    in
    {
      packages = forAll (pkgs: rec {
        default = pkgs.callPackage ./nix/package.nix {
          venv = (pythonSetFor pkgs).mkVirtualEnv "mingadocs-env" workspace.deps.default;
        };
        mingadocs = default;
      });

      nixosModules.default = import ./nix/module.nix { inherit self; };

      checks = forAll (
        pkgs:
        let
          package = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
        in
        {
          inherit package;
          # The unit tests, against the packaged app with DEBUG off - i.e. the
          # same code and settings path production runs. The OCR regression
          # suite needs real scans and stays a local-only `make` target.
          tests = pkgs.runCommand "mingadocs-tests" { } ''
            export HOME=$TMPDIR
            export MINGADOCS_DEBUG=0
            export MINGADOCS_SECRET_KEY_FILE=$TMPDIR/key
            echo test-only-secret-key-not-the-dev-one > $MINGADOCS_SECRET_KEY_FILE
            export MINGADOCS_DB_PATH=$TMPDIR/db.sqlite3
            export MINGADOCS_MEDIA_ROOT=$TMPDIR/media
            export MINGADOCS_ALLOWED_HOSTS=testserver
            ${package}/bin/mingadocs-manage test arnlabels scans siteconfig
            touch $out
          '';
        }
        // lib.optionalAttrs (pkgs.stdenv.hostPlatform.system == "x86_64-linux") {
          vm = import ./nix/vm-test.nix { inherit pkgs self; };
        }
      );

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.python314
            pkgs.sane-backends
          ];
          env = {
            UV_PYTHON = pkgs.python314.interpreter;
            UV_PYTHON_DOWNLOADS = "never";
          };
        };
      });
    };
}
