<?php
// Thin bridge to Composer's maintained class-map implementation, not a PHP parser.
require $argv[1];
if (!class_exists(Composer\ClassMapGenerator\ClassMapGenerator::class)) {
    fwrite(STDERR, "Install composer/class-map-generator or provide a native JSON inventory bridge.\n");
    exit(1);
}
$files = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$generator = new Composer\ClassMapGenerator\ClassMapGenerator();
$generator->avoidDuplicateScans();
foreach ($files as $file) { $generator->scanPaths($file); }
$map = $generator->getClassMap();
if ($map->getAmbiguousClasses()) { fwrite(STDERR, "Ambiguous class declarations\n"); exit(1); }
echo json_encode($map->getMap(), JSON_THROW_ON_ERROR);
