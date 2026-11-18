{ pkgs }:

# Fix-ups for packages uv2nix can't build from uv.lock alone.
final: prev: {
  # Only published as an sdist; it compiles against libcups.
  pycups = prev.pycups.overrideAttrs (old: {
    nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ final.resolveBuildSystem { setuptools = [ ]; };
    buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.cups ];
  });
}
