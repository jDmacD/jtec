{
  description = "jtec cli";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

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

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    uv2nix,
    pyproject-nix,
    pyproject-build-systems,
    ...
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      inherit (nixpkgs) lib;
      inherit (pkgs.callPackages pyproject-nix.build.util {}) mkApplication;
      workspace = uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

      # Create package overlay from workspace.
      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      pyprojectOverrides = _final: _prev: {};

      pkgs = nixpkgs.legacyPackages.${system};
      python = pkgs.python313;

      # Construct package set
      pythonSet =
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope
        (
          lib.composeManyExtensions [
            pyproject-build-systems.overlays.default
            overlay
            pyprojectOverrides
          ]
        );
    in {
      formatter = nixpkgs.legacyPackages.${system}.alejandra;
      packages = {
        default = mkApplication {
          venv = pythonSet.mkVirtualEnv "jtec-env" workspace.deps.default;
          package = pythonSet.jtec;
        };
        # Keep the full env as a separate package
        jtec-env = pythonSet.mkVirtualEnv "jtec-env" workspace.deps.default;

        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "jtec";
          tag = "latest";
          created = "now";
          contents = [];
          config = {
            Cmd = [
              "${self.packages.${system}.default}/bin/jtec"
            ];
            Env = [];
          };
        };
      };
      apps.default = {
        type = "app";
        program = "${self.packages.${system}.default}/bin/jtec";
      };

      devShells = {
        uv2nix = let
          editableOverlay = workspace.mkEditablePyprojectOverlay {
            root = "$REPO_ROOT";
          };

          editablePythonSet = pythonSet.overrideScope (
            lib.composeManyExtensions [
              editableOverlay

              (final: prev: {
                jtec = prev.jtec.overrideAttrs (old: {
                  src = lib.fileset.toSource {
                    root = old.src;
                    fileset = lib.fileset.unions [
                      (old.src + "/pyproject.toml")
                      (old.src + "/README.md")
                      (old.src + "/src/jtec/__init__.py")
                    ];
                  };
                  nativeBuildInputs =
                    old.nativeBuildInputs
                    ++ final.resolveBuildSystem {
                      editables = [];
                    };
                });
              })
            ]
          );
          virtualenv = editablePythonSet.mkVirtualEnv "jtec-dev-env" workspace.deps.all;
        in
          pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
            ];

            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = "${virtualenv}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
      };
    });
}
