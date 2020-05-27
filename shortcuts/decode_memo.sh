echo $1 | python3 -c 'import zlib, binascii, urllib.parse, sys; memo = sys.stdin.readline(); memo = memo.split("_", 1)[1]; "## drop ln.support_ memo prefix"; memo = memo.rstrip("/"); "## drop trailing /"; memo = urllib.parse.unquote(memo); "## url encdoding"; decoded = zlib.decompress(binascii.a2b_base64(memo)).decode("utf-8"); print(decoded); ' | python3 -m json.tool

