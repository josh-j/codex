let
  system =
    if builtins ? currentSystem then
      builtins.currentSystem
    else
      builtins.readFile /etc/nix/system;

  flake = builtins.getFlake (toString ./.);
in
flake.devShells.${system}.default
