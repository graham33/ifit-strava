with import <nixpkgs> {};
with python38Packages;

let
  stravalib_patched = stravalib.overrideAttrs(o: {
    src = fetchFromGitHub {
      owner = "graham33";
      repo = "stravalib";
      rev = "acc8a6657e9356595dc8c527c261f0c59b85168a";
      sha256 = "1dv7fd5kc4syrks0vbgk6l3k2857lj7sjgwi40v8jgxjkd0xj69w";
    };
  });

  tcxparser = buildPythonPackage rec {
    pname = "python-tcxparser";
    version = "1.1.0";

    src = fetchPypi {
      inherit pname version;
      sha256 = "1v868dcfxxjx2f3gkr14ldvq9093zjp7l0x4gbdfkb1lwj0fmzjz";
    };

    propagatedBuildInputs = [ lxml ];

    meta = with lib; {
      homepage = https://github.com/vkurup/python-tcxparser/;
      description = "Simple parser for Garmin TCX files";
      license = licenses.bsd2;
    };
  };

in
  buildPythonPackage rec {
    name = "ifit_strava";
    src = ".";
    propagatedBuildInputs = [ click
                              flask
                              flake8
                              lxml
                              pytest
                              pyyaml
                              requests
                              stravalib_patched
                              tcxparser
                              yapf
                            ];
  }
