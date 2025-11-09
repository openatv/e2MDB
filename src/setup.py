from setuptools import setup
import setup_translate

pkg = 'Extensions.e2MDB'
setup(name='enigma2-plugin-extensions-e2mdb',
       version='1.0',
       description='e2MDB for E2',
       package_dir={pkg: 'e2MDB'},
       packages=[pkg],
       package_data={pkg: ['images/*.png', '*.png', '*.xml', 'locale/*/LC_MESSAGES/*.mo']},
       cmdclass=setup_translate.cmdclass,  # for translation
      )
