#!/bin/sh
# Compile the Java helpers to smali: javac -> d8 -> apktool (baksmali).
# usage: compile_java.sh <java-src-dir> <android.jar> <tools-dir> <smali-out-dir>
set -e
SRC=$1 AJ=$2 T=$3 OUT=$4
JB=$(dirname "$(find "$T" -path '*bin/javac' | head -1)")
D8=$(find "$T" -name d8 -type f | head -1)
APKTOOL=$(find "$T" -name 'apktool*.jar' | head -1)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
find "$SRC" -name '*.java' > "$TMP/files"
"$JB/javac" -source 8 -target 8 -bootclasspath "$AJ" -cp "$AJ" -Xlint:-options -nowarn -d "$TMP/classes" @"$TMP/files"
mkdir -p "$TMP/dex"
PATH="$JB:$PATH" "$D8" --lib "$AJ" --min-api 28 --output "$TMP/dex" $(find "$TMP/classes" -name '*.class')
python3 -I -c "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1], 'w'); z.write(sys.argv[2], 'classes.dex'); z.close()" "$TMP/dex.apk" "$TMP/dex/classes.dex"
"$JB/java" -jar "$APKTOOL" d -r -f -q "$TMP/dex.apk" -o "$TMP/out"
mkdir -p "$OUT"
for f in "$TMP"/out/smali/com/uvp/*.smali; do
    cp "$f" "$OUT/"
    echo "  $(basename "$f")"
done
