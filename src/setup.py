from setuptools import setup
import setup_translate

pkg = "Extensions.e2MDB"
provider_pkg = "Extensions.e2MDB.provider"

setup(name="enigma2-plugin-extensions-e2mdb",
       version="1.0",
       description="e2MDB for E2",
       package_dir={
           pkg: "e2MDB",
           provider_pkg: "e2MDB/provider",
       },
       packages=[pkg, provider_pkg],
       package_data={
           pkg: ["images/*.png", "web/index.html", "*.png", "*.xml", "locale/*/LC_MESSAGES/*.mo"],
           provider_pkg: ["*.txt"],
       },
       data_files=[
           ("/etc/init.d", ["init.d/e2mdbd"]),
           ("/usr/lib/enigma2/python/Components/Converter", ["Components/Converter/E2MDBEventInfo.py"]),
       ],
       cmdclass=setup_translate.cmdclass,  # for translation
      )
