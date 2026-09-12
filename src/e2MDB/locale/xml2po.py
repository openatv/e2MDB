from sys import argv
from os import listdir
from os.path import basename, isdir, join
from re import compile
from xml.sax import make_parser
from xml.sax.handler import ContentHandler, LexicalHandler, property_lexical_handler


class parse_xml(ContentHandler, LexicalHandler):
	def __init__(self, attributes):
		self.attributes = attributes
		self.lastComment = None
		self.isHex = compile(r'#[0-9a-fA-F]+\Z')

	def comment(self, comment):
		if "TRANSLATORS:" in comment:
			self.lastComment = comment

	def startElement(self, tag, attribs):
		for attribute in ["text", "title", "value", "caption", "description", "red", "green", "yellow", "blue"]:  # Attributes that need to be translated.
			try:
				value = attribs[attribute]
				if value.strip() != "" and not self.isHex.match(value):
					attributes.add((value, self.lastComment))
					self.lastComment = None
			except KeyError:
				pass


excludeFiles = ["dnsservers.xml"]

parser = make_parser()
attributes = set()
content_handler = parse_xml(attributes)
parser.setContentHandler(content_handler)
parser.setProperty(property_lexical_handler, content_handler)
for arg in argv[1:]:
	if isdir(arg):
		files = [join(arg, f) for f in listdir(arg) if f.endswith(".xml")]
	else:
		files = [arg]
	for file in files:
		if basename(file) not in excludeFiles:
			parser.parse(file)
	attributes = list(attributes)
	attributes.sort(key=lambda x: x[0])
	for (key, value) in attributes:
		print(f"\n#: {arg}")
		key.replace("\\n", "\"\n\"")
		if value:
			for line in value.split("\n"):
				print(f"#. {line}")
		print(f"msgid \"{key}\"")
		print("msgstr \"\"")
	attributes = set()
