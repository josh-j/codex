{
  description = "Ansible NCS - Infrastructure Health Monitoring";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        pythonEnv = pkgs.python3.withPackages (ps:
          with ps; [
            ansible-core
            pywinrm
            pyvmomi
            jinja2
            pyyaml
          ]);
      in {
        devShells.default = pkgs.mkShell {
          name = "ansible-ncs-dev";

          packages = with pkgs; [
            pythonEnv
            ansible-lint
            yamllint
            gnumake
            pandoc
            git
            shellcheck
          ];

          shellHook = ''
            echo "Ansible NCS development environment"
            echo "Ansible: $(ansible --version | head -1)"

            export ANSIBLE_CONFIG="$PWD/ansible.cfg"
            export ANSIBLE_COLLECTIONS_PATH="$PWD/collections:$HOME/.ansible/collections''${ANSIBLE_COLLECTIONS_PATH:+:$ANSIBLE_COLLECTIONS_PATH}"
            export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
          '';
        };
      });
}
