{
  lib,
  stdenvNoCC,
  makeWrapper,
  venv,
}:

# The Django project plus its virtualenv. Exposes:
#   bin/mingadocs-manage    manage.py, for migrate / shell / createsuperuser ...
#   bin/mingadocs-gunicorn  the WSGI server, already pointed at the project
#   share/mingadocs/static  collected static files, for the front web server
stdenvNoCC.mkDerivation {
  pname = "mingadocs";
  version = "0.1.0";

  # Only the app itself: never a local db.sqlite3 or media/ that happen to sit
  # next to it in a working tree.
  src = lib.fileset.toSource {
    root = ../src/mingadocs;
    fileset = lib.fileset.unions [
      ../src/mingadocs/manage.py
      ../src/mingadocs/config
      ../src/mingadocs/arnlabels
      ../src/mingadocs/scans
      ../src/mingadocs/siteconfig
    ];
  };

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    app=$out/share/mingadocs/app
    mkdir -p $app $out/bin
    cp -r . $app

    MINGADOCS_STATIC_ROOT=$out/share/mingadocs/static \
      ${venv}/bin/python $app/manage.py collectstatic --noinput

    makeWrapper ${venv}/bin/python $out/bin/mingadocs-manage \
      --add-flags $app/manage.py
    makeWrapper ${venv}/bin/gunicorn $out/bin/mingadocs-gunicorn \
      --add-flags "--chdir $app config.wsgi:application"

    runHook postInstall
  '';

  passthru = { inherit venv; };

  meta = {
    description = "Scan, number and file paper documents, and print their ARN labels";
    mainProgram = "mingadocs-gunicorn";
    platforms = lib.platforms.linux;
  };
}
