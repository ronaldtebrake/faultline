<?php
// Read source as data. Never include, autoload, or evaluate consumer code.
if (in_array('--match', $argv, true)) {
    $data = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
    $output = [];
    foreach ($data['steps'] as $step) {
        $found = [];
        $uncertain = false;
        foreach ($data['patterns'] as $index => $pattern) {
            if (str_starts_with($pattern, '/^') || str_starts_with($pattern, '~^') || str_starts_with($pattern, '#^')) {
                $result = @preg_match($pattern, $step);
                if ($result === false) $uncertain = true;
                elseif ($result === 1) $found[] = $index;
            } elseif (!str_contains($pattern, ':') && !str_contains($pattern, '{')) {
                if ($pattern === $step) $found[] = $index;
            } else {
                // Turnip parameters and custom transforms need Behat resolution.
                $uncertain = true;
            }
        }
        $output[] = ['matches' => $found, 'unresolved_patterns' => $uncertain];
    }
    echo json_encode($output, JSON_THROW_ON_ERROR);
    exit;
}
// `php -n` keeps project and machine INI hooks out of source analysis. Some
// distributions ship tokenizer as a shared module instead of compiling it in.
// Load only that installed PHP extension, never a path supplied by source text.
if (!function_exists('token_get_all')) {
    $extension = (PHP_SHLIB_SUFFIX === 'dll' ? 'php_' : '') . 'tokenizer.' . PHP_SHLIB_SUFFIX;
    if (!function_exists('dl') || !@dl($extension) || !function_exists('token_get_all')) {
        fwrite(STDERR, "Faultline requires the PHP tokenizer extension.\n");
        exit(78);
    }
}
function declaration_fingerprint(array $tokens): string {
    // Preserve declarations, attributes and registration/configuration outside
    // function bodies. Do not execute source or infer routes from conventions.
    $parts = [];
    $count = count($tokens);
    for ($i = 0; $i < $count; ++$i) {
        $token = $tokens[$i];
        if (is_array($token) && in_array($token[0], [T_WHITESPACE, T_COMMENT], true)) continue;
        $parts[] = is_array($token) ? [$token[0], $token[1]] : $token;
        if (!is_array($token) || $token[0] !== T_FUNCTION) continue;
        $next = $i + 1;
        while ($next < $count && ((is_array($tokens[$next]) && in_array($tokens[$next][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) || (is_array($tokens[$next]) ? $tokens[$next][1] : $tokens[$next]) === '&')) ++$next;
        if ($next < $count && is_array($tokens[$next]) && $tokens[$next][0] === T_STRING) {
            do { ++$next; } while ($next < $count && is_array($tokens[$next]) && in_array($tokens[$next][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true));
        }
        // `use function Name;` is a registration, not a function body.
        if ($next >= $count || $tokens[$next] !== '(') continue;
        // The parameter list can contain attributes, arrays and interpolated
        // strings. Only a brace after its closing parenthesis starts the body.
        $parentheses = 0;
        $parameters = false;
        for (++$i; $i < $count; ++$i) {
            $token = $tokens[$i];
            if ($token === '(') { ++$parentheses; $parameters = true; }
            if ($token === ')') --$parentheses;
            if (is_array($token) && in_array($token[0], [T_WHITESPACE, T_COMMENT], true)) continue;
            $parts[] = is_array($token) ? [$token[0], $token[1]] : $token;
            if ($parameters && $parentheses === 0 && ($token === '{' || $token === ';')) break;
        }
        if ($i >= $count || $tokens[$i] !== '{') continue;
        $depth = 1;
        $body = [];
        $nestedDeclaration = false;
        for (++$i; $i < $count; ++$i) {
            $token = $tokens[$i];
            if ($token === '{' || (is_array($token) && in_array($token[0], [T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES], true))) ++$depth;
            if ($token === '}' && --$depth === 0) break;
            if (is_array($token) && in_array($token[0], [T_FUNCTION, T_CLASS, T_INTERFACE, T_TRAIT, T_ENUM], true)) {
                $next = $i + 1;
                while ($next < $count && ((is_array($tokens[$next]) && in_array($tokens[$next][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) || (is_array($tokens[$next]) ? $tokens[$next][1] : $tokens[$next]) === '&')) ++$next;
                // Named declarations inside functions can change global symbols.
                if ($next < $count && is_array($tokens[$next]) && $tokens[$next][0] === T_STRING) $nestedDeclaration = true;
            }
            if (is_array($token) && in_array($token[0], [T_WHITESPACE, T_COMMENT], true)) continue;
            $body[] = is_array($token) ? [$token[0], $token[1]] : $token;
        }
        if ($nestedDeclaration || $depth !== 0) $parts[] = $body;
        $parts[] = '}';
    }
    return hash('sha256', json_encode($parts, JSON_THROW_ON_ERROR));
}

function source_facts(string $source): array {
$tokens = token_get_all($source);
$classes = $references = $definitions = $gaps = [];
$namespace = '';
$aliases = [];
$doc = '';
$attributes = '';
$class = '';
$brace = 0;
$classDepth = null;
$pendingClass = false;
$count = count($tokens);
$text = fn($token) => is_array($token) ? $token[1] : $token;
$isName = fn($token) => is_array($token) && in_array($token[0], [T_STRING, T_NAME_QUALIFIED, T_NAME_FULLY_QUALIFIED, T_NAME_RELATIVE], true);
$next = function ($i) use ($tokens, $count) {
    do { ++$i; } while ($i < $count && is_array($tokens[$i]) && in_array($tokens[$i][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true));
    return $i;
};
$resolve = function ($name) use (&$namespace, &$aliases) {
    if (str_starts_with($name, '\\')) return ltrim($name, '\\');
    if (str_starts_with($name, 'namespace\\')) return trim($namespace . '\\' . substr($name, 10), '\\');
    $parts = explode('\\', $name);
    $alias = $aliases[strtolower($parts[0])] ?? null;
    if ($alias !== null) return $alias . (count($parts) > 1 ? '\\' . implode('\\', array_slice($parts, 1)) : '');
    return trim($namespace . '\\' . $name, '\\');
};
for ($i = 0; $i < $count; ++$i) {
    $token = $tokens[$i];
    if ($token === '{') { ++$brace; if ($pendingClass) { $classDepth = $brace; $pendingClass = false; } continue; }
    if ($token === '}') { if ($classDepth === $brace) { $classDepth = null; $class = ''; } --$brace; continue; }
    if (!is_array($token)) continue;
    [$id, $value, $line] = $token;
    if ($id === T_NAMESPACE) {
        $j = $next($i); $namespace = $j < $count && $isName($tokens[$j]) ? trim($text($tokens[$j]), '\\') : '';
        $aliases = []; $i = $j; continue;
    }
    if ($id === T_USE && $classDepth === null && $brace === 0) {
        $use = ''; $j = $i + 1;
        for (; $j < $count && $tokens[$j] !== ';'; ++$j) $use .= $text($tokens[$j]);
        if (str_contains($use, '{') || preg_match('/^\s*(function|const)\b/', $use)) $gaps[] = 'unsupported_php_use';
        else foreach (explode(',', $use) as $part) {
            if (preg_match('/^\s*([\\\\\w]+)(?:\s+as\s+(\w+))?\s*$/i', $part, $m)) {
                $fq = ltrim($m[1], '\\'); $pieces = explode('\\', $fq);
                $aliases[strtolower($m[2] ?? end($pieces))] = $fq;
            } else $gaps[] = 'unsupported_php_use';
        }
        $i = $j; continue;
    }
    if (in_array($id, [T_CLASS, T_INTERFACE, T_TRAIT, T_ENUM], true)) {
        $j = $next($i);
        if ($j < $count && is_array($tokens[$j]) && $tokens[$j][0] === T_STRING) {
            $class = trim($namespace . '\\' . $text($tokens[$j]), '\\');
            $classes[] = $class; $pendingClass = true; $i = $j;
        }
        continue;
    }
    if ($id === T_DOC_COMMENT) { $doc = $value; continue; }
    if ($id === T_ATTRIBUTE) {
        $attributes .= $value; $depth = 1;
        while (++$i < $count && $depth > 0) {
            if ($tokens[$i] === '[') ++$depth;
            if ($tokens[$i] === ']') --$depth;
            $attributes .= $text($tokens[$i]);
        }
        --$i; continue;
    }
    if ($id === T_FUNCTION) {
        $j = $next($i);
        if ($j < $count && $text($tokens[$j]) === '&') $j = $next($j);
        $method = $j < $count && is_array($tokens[$j]) && $tokens[$j][0] === T_STRING ? $text($tokens[$j]) : '';
        $patterns = [];
        if ($method !== '' && $class !== '') {
            preg_match_all('/@(Given|When|Then)\s+([^\r\n]+)/', $doc, $matches, PREG_SET_ORDER);
            foreach ($matches as $m) $patterns[] = trim(preg_replace('/\s*\*\/$/', '', $m[2]));
            preg_match_all('/(?:Given|When|Then)\s*\(\s*([\'\"])((?:\\\\.|(?!\1).)*)\1\s*\)/s', $attributes, $matches, PREG_SET_ORDER);
            foreach ($matches as $m) {
                // Decode the limited constant-string form; never eval attributes.
                $pattern = $m[2];
                if ($m[1] === "'") $pattern = str_replace(["\\'", '\\\\'], ["'", '\\'], $pattern);
                else { $gaps[] = 'double_quoted_step_attribute'; continue; }
                $patterns[] = $pattern;
            }
            foreach ($patterns as $pattern) $definitions[] = ['pattern' => $pattern, 'symbol' => $class . '::' . $method, 'line' => $line];
        }
        $doc = $attributes = '';
    }
    // Resolve names only in type/class positions. A method named like a class
    // must not introduce a dependency on that unrelated class.
    if ($isName($token) && !in_array(strtolower($value), ['self', 'static', 'parent'], true)) {
        $previous = $i - 1;
        while ($previous >= 0 && is_array($tokens[$previous]) && in_array($tokens[$previous][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) --$previous;
        $prior = $previous >= 0 ? $tokens[$previous] : null;
        $j = $next($i); $following = $j < $count ? $tokens[$j] : null;
        $classPosition = is_array($prior) && in_array($prior[0], [T_NEW, T_EXTENDS, T_IMPLEMENTS, T_INSTANCEOF, T_USE], true);
        $typePosition = is_array($following) && in_array($following[0], [T_VARIABLE, T_DOUBLE_COLON], true);
        $returnPosition = $prior === ':' || $prior === '?' || $prior === '|' || $prior === '&';
        if ($classPosition || $typePosition || $returnPosition) $references[] = $resolve($value);
    }
}
$gaps[] = 'php_dynamic_dispatch_requires_additional_evidence';
return ['classes' => array_values(array_unique($classes)), 'references' => array_values(array_unique($references)),
        'declaration_hash' => declaration_fingerprint($tokens),
        'definitions' => $definitions, 'gaps' => array_values(array_unique($gaps))];
}
$input = stream_get_contents(STDIN);
$output = in_array('--batch', $argv, true)
    ? array_map('source_facts', json_decode($input, true, 512, JSON_THROW_ON_ERROR))
    : source_facts($input);
echo json_encode($output, JSON_THROW_ON_ERROR);
