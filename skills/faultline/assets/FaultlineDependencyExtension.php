<?php
/** Observe native Behat 3 events during an existing run. No test hooks are added. */
namespace Faultline\Dependencies;

use Behat\Behat\EventDispatcher\Event\FeatureTested;
use Behat\Behat\EventDispatcher\Event\ExampleTested;
use Behat\Behat\EventDispatcher\Event\ScenarioTested;
use Behat\Behat\EventDispatcher\Event\StepTested;
use Behat\Behat\Tester\Result\DefinedStepResult;
use Behat\Behat\Tester\Result\ExecutedStepResult;
use Behat\Testwork\EventDispatcher\Event\SuiteTested;
use Behat\Testwork\EventDispatcher\ServiceContainer\EventDispatcherExtension;
use Behat\Testwork\Hook\Tester\Setup\HookedSetup;
use Behat\Testwork\Hook\Tester\Setup\HookedTeardown;
use Behat\Testwork\ServiceContainer\Extension;
use Behat\Testwork\ServiceContainer\ExtensionManager;
use Behat\Testwork\Tester\Result\TestResult;
use Symfony\Component\Config\Definition\Builder\ArrayNodeDefinition;
use Symfony\Component\DependencyInjection\ContainerBuilder;
use Symfony\Component\DependencyInjection\Definition;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

final class DependencySubscriber implements EventSubscriberInterface
{
    private ?array $context = null;
    private array $suite = [];
    private array $features = [];
    private array $records = [];
    private ?array $scenario = null;
    private array $sourceLines = [];
    private array $sourceHashes = [];
    private bool $inSuite = false;
    private ?string $currentFeature = null;

    public function __construct()
    {
        $path = getenv('FAULTLINE_DEPENDENCY_CONTEXT');
        if (!$path) return;
        $this->context = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
        if (($this->context['runner'] ?? null) !== 'behat' || !getenv('FAULTLINE_DEPENDENCY_OUTPUT')) {
            throw new \RuntimeException('Faultline requires a Behat dependency context and output directory');
        }
    }

    public static function getSubscribedEvents(): array
    {
        return [SuiteTested::BEFORE => 'suiteStart', SuiteTested::AFTER_SETUP => 'suiteSetup',
                SuiteTested::AFTER => 'suiteFinish', FeatureTested::BEFORE => 'featureStart',
                FeatureTested::AFTER_SETUP => 'featureSetup', FeatureTested::AFTER => 'featureFinish',
                ScenarioTested::BEFORE => 'scenarioStart', ScenarioTested::AFTER_SETUP => 'scenarioSetup',
                ScenarioTested::AFTER => 'scenarioFinish', ExampleTested::BEFORE => 'scenarioStart',
                ExampleTested::AFTER_SETUP => 'scenarioSetup', ExampleTested::AFTER => 'scenarioFinish',
                StepTested::AFTER_SETUP => 'stepSetup',
                StepTested::AFTER => 'stepFinish',
                'faultline.http_request' => 'requestAttempted'];
    }

    private function bucket(): array { return ['files' => [], 'callables' => [], 'source_hashes' => [], 'resources' => [], 'gaps' => [], 'hook_failure' => false]; }

    public function requestAttempted($event): void
    {
        if ($this->context === null || !$this->inSuite) return;
        if ($this->scenario !== null) $bucket =& $this->scenario;
        elseif ($this->currentFeature !== null) $bucket =& $this->features[$this->currentFeature];
        else $bucket =& $this->suite;
        try {
            $method = is_callable([$event, 'getMethod']) ? $event->getMethod() : null;
            $url = is_callable([$event, 'getUrl']) ? $event->getUrl() : null;
        } catch (\Throwable $error) {
            $bucket['gaps'][] = 'An explicit HTTP request could not be attributed.';
            return;
        }
        $parts = is_string($url) && preg_match('//u', $url) === 1 && !preg_match('/[\x00-\x1f]/', $url)
            ? parse_url($url) : false;
        if (!is_string($method) || !preg_match('/^[a-z]+$/i', $method) || !is_array($parts) ||
            !in_array(strtolower($parts['scheme'] ?? ''), ['http', 'https'], true) || empty($parts['host'])) {
            $bucket['gaps'][] = 'An explicit HTTP request could not be attributed.';
            return;
        }
        // Store neither the URL authority nor query, fragment, headers or body.
        $item = ['kind' => 'http_request', 'method' => strtoupper($method), 'path' => $parts['path'] ?? '/'];
        $bucket['resources'][json_encode($item, JSON_THROW_ON_ERROR)] = $item;
        $bucket['gaps'][] = 'Explicit HTTP observations describe attempts, not server-side execution.';
    }

    private function relative(string $file): ?string
    {
        $file = str_replace('\\', '/', realpath($file) ?: $file);
        $matches = [];
        $mounts = array_merge([['root' => $this->context['root'], 'prefix' => '']], $this->context['mounts'] ?? []);
        foreach ($mounts as $mount) {
            $root = rtrim(str_replace('\\', '/', realpath($mount['root']) ?: $mount['root']), '/') . '/';
            if (!str_starts_with($file, $root)) continue;
            $path = ($mount['prefix'] === '' ? '' : $mount['prefix'] . '/') . substr($file, strlen($root));
            $matches[$path] = true;
        }
        if (count($matches) > 1) throw new \RuntimeException('Ambiguous Faultline runtime source mapping');
        $path = array_key_first($matches);
        return $path !== null && array_key_exists($path, $this->context['tree']) ? $path : null;
    }

    private function source(array &$bucket, string $file, string $source): array
    {
        if (!array_key_exists($file, $this->sourceLines)) {
            $lines = file($file);
            if ($lines === false) throw new \RuntimeException('Cannot read native source for dependency evidence');
            $this->sourceLines[$file] = $lines;
            $this->sourceHashes[$file] = hash('sha256', implode('', $lines));
        }
        $hash = $this->sourceHashes[$file];
        if (isset($bucket['source_hashes'][$source]) && $bucket['source_hashes'][$source] !== $hash) {
            throw new \RuntimeException('Different runtime files map to one repository source');
        }
        $bucket['source_hashes'][$source] = $hash;
        return $this->sourceLines[$file];
    }

    private function callable(array &$bucket, \ReflectionFunctionAbstract $reflection, string $role, string $execution): void
    {
        $file = $reflection->getFileName();
        $source = $file ? $this->relative($file) : null;
        if ($source === null) {
            $bucket['gaps'][] = 'A native ' . $role . ' callable is outside tracked repository source.';
            return;
        }
        $bucket['files'][$source] = true;
        $start = $reflection->getStartLine();
        $end = $reflection->getEndLine();
        $symbol = $reflection instanceof \ReflectionMethod
            ? $reflection->getDeclaringClass()->getName() . '::' . $reflection->getName()
            : $reflection->getName();
        $lines = $this->source($bucket, $file, $source);
        if (!$start || !$end || $end < $start || $end > count($lines) || str_contains($symbol, "\0")) {
            $bucket['gaps'][] = 'A native callable source range is unavailable.';
            return;
        }
        $item = ['source' => $source, 'symbol' => $symbol, 'start_line' => $start, 'end_line' => $end,
                 'sha256' => hash('sha256', implode('', array_slice($lines, $start - 1, $end - $start + 1))),
                 'role' => $role, 'execution' => $execution];
        $bucket['callables'][json_encode($item, JSON_THROW_ON_ERROR)] = $item;
        if (count($bucket['callables']) > 4096) throw new \RuntimeException('Faultline callable evidence exceeds its limit');
    }

    private function hooks(array &$bucket, $result, string $role): void
    {
        $bucket['hook_failure'] = $bucket['hook_failure'] || !$result->isSuccessful();
        if (!$result instanceof HookedSetup && !$result instanceof HookedTeardown) {
            $bucket['gaps'][] = 'Native hook results are unavailable for ' . $role . '.';
            return;
        }
        foreach ($result->getHookCallResults() as $call) {
            $this->callable($bucket, $call->getCall()->getCallee()->getReflection(), $role, 'called');
        }
    }

    public function suiteStart($event): void
    {
        if ($this->context === null) return;
        $this->suite = $this->bucket();
        $this->features = $this->records = [];
        $this->sourceLines = $this->sourceHashes = [];
        $this->scenario = null;
        $this->currentFeature = null;
        $this->inSuite = true;
    }

    public function suiteSetup($event): void
    {
        if ($this->context !== null) $this->hooks($this->suite, $event->getSetup(), 'before_suite');
    }

    public function featureStart($event): void
    {
        if ($this->context !== null) {
            $this->currentFeature = $event->getFeature()->getFile();
            $this->features[$this->currentFeature] = $this->bucket();
        }
    }

    public function featureSetup($event): void
    {
        if ($this->context !== null) $this->hooks($this->features[$event->getFeature()->getFile()], $event->getSetup(), 'before_feature');
    }

    public function featureFinish($event): void
    {
        if ($this->context !== null) $this->hooks($this->features[$event->getFeature()->getFile()], $event->getTeardown(), 'after_feature');
        $this->currentFeature = null;
    }

    public function scenarioStart($event): void
    {
        if ($this->context === null) return;
        $this->scenario = null;
        $source = $this->relative($event->getFeature()->getFile());
        if ($source === null || !in_array($source, $this->context['sources'], true)) return;
        $this->scenario = $this->bucket() + [
            'test_source' => $source,
            'test_identity' => json_encode([$event->getSuite()->getName(), $source, $event->getScenario()->getLine()], JSON_THROW_ON_ERROR),
            'feature' => $event->getFeature()->getFile(),
        ];
        $this->scenario['gaps'] = ['External browser/server execution is not covered by this PHP process.',
                                 'Native callables do not describe helper calls, context construction or argument transforms.'];
        $this->source($this->scenario, $event->getFeature()->getFile(), $source);
    }

    public function scenarioSetup($event): void
    {
        if ($this->scenario !== null) $this->hooks($this->scenario, $event->getSetup(), 'before_scenario');
    }

    public function stepSetup($event): void
    {
        if ($this->scenario !== null) $this->hooks($this->scenario, $event->getSetup(), 'before_step');
    }

    public function stepFinish($event): void
    {
        if ($this->scenario === null) return;
        $result = $event->getTestResult();
        if ($result instanceof DefinedStepResult && $result->getStepDefinition() !== null) {
            $execution = $result instanceof ExecutedStepResult ? 'called' : 'resolved';
            $this->callable($this->scenario, $result->getStepDefinition()->getReflection(), 'step', $execution);
        } else {
            $this->scenario['gaps'][] = 'A step definition was not resolved.';
        }
        $this->hooks($this->scenario, $event->getTeardown(), 'after_step');
    }

    public function scenarioFinish($event): void
    {
        if ($this->scenario === null) return;
        $this->hooks($this->scenario, $event->getTeardown(), 'after_scenario');
        $result = $event->getTestResult();
        $this->scenario['status'] = $result->isPassed() ? 'passed'
            : ($result->getResultCode() === TestResult::SKIPPED ? 'skipped' : 'failed');
        $this->records[] = $this->scenario;
        $this->scenario = null;
        if (count($this->records) > 100000) throw new \RuntimeException('Faultline scenario evidence exceeds its limit');
    }

    public function suiteFinish($event): void
    {
        if ($this->context === null) return;
        $this->hooks($this->suite, $event->getTeardown(), 'after_suite');
        foreach ($this->sourceHashes as $file => $expected) {
            if (hash_file('sha256', $file) !== $expected) {
                throw new \RuntimeException('Native callable source changed during dependency collection');
            }
        }
        // Write after suite teardown so even after-feature/after-suite hooks are
        // attributed to the scenarios they enclosed. Interrupted runs may have
        // no artifact; collection never asserts that a baseline is complete.
        foreach ($this->records as $record) {
            foreach ([$this->features[$record['feature']], $this->suite] as $parent) {
                $record['files'] += $parent['files'];
                $record['callables'] += $parent['callables'];
                $record['resources'] += $parent['resources'];
                foreach ($parent['source_hashes'] as $source => $hash) {
                    if (isset($record['source_hashes'][$source]) && $record['source_hashes'][$source] !== $hash) {
                        throw new \RuntimeException('Different runtime files map to one repository source');
                    }
                    $record['source_hashes'][$source] = $hash;
                }
                $record['gaps'] = array_merge($record['gaps'], $parent['gaps']);
                $record['hook_failure'] = $record['hook_failure'] || $parent['hook_failure'];
            }
            if ($record['hook_failure']) {
                $record['status'] = 'failed';
                $record['gaps'][] = 'Scenario or enclosing feature/suite setup or teardown failed.';
            }
            unset($record['feature'], $record['hook_failure']);
            $record['files'] = array_keys($record['files']);
            $record['callables'] = array_values($record['callables']);
            $record['resources'] = array_values($record['resources']);
            $record['gaps'] = array_values(array_unique($record['gaps']));
            $record += ['version' => 1, 'context' => $this->context['integrity'], 'producer' => 'behat', 'resources' => []];
            $directory = getenv('FAULTLINE_DEPENDENCY_OUTPUT');
            if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) {
                throw new \RuntimeException('Cannot create dependency evidence directory');
            }
            $file = $directory . '/behat-' . bin2hex(random_bytes(12)) . '.json';
            if (file_put_contents($file, json_encode($record, JSON_THROW_ON_ERROR)) === false) {
                throw new \RuntimeException('Cannot persist dependency evidence');
            }
        }
        $this->features = $this->records = $this->suite = [];
        $this->inSuite = false;
    }
}

return new class implements Extension {
    public function getConfigKey() { return 'faultline_dependencies'; }
    public function initialize(ExtensionManager $extensionManager) {}
    public function configure(ArrayNodeDefinition $builder) {}
    public function load(ContainerBuilder $container, array $config)
    {
        $definition = new Definition(DependencySubscriber::class);
        $definition->addTag(EventDispatcherExtension::SUBSCRIBER_TAG);
        $container->setDefinition('faultline.dependencies', $definition);
    }
    public function process(ContainerBuilder $container): void {}
};
