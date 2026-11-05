{
  description = "til — a personal daily-notes / TIL site";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          # The build script is pure-stdlib Python; math is rendered client-side
          # by MathJax, so the shell stays intentionally small.
          packages = [ pkgs.python3 pkgs.gnumake ];

          shellHook = ''
            echo "til — dev shell"
            echo "  make new      scaffold today's record in records/"
            echo "  make build    generate the static site into docs/"
            echo "  make serve    build, then preview at http://localhost:8000"
            echo "  make clean    remove docs/"
          '';
        };
      });
}
