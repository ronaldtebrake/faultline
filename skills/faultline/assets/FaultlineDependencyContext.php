<?php
/** Add this context to an existing Behat suite to collect positive dependency evidence. */
use Behat\Behat\Context\Context;
use Behat\Behat\Hook\Scope\AfterScenarioScope;
use Behat\Behat\Hook\Scope\AfterStepScope;
use Behat\Behat\Hook\Scope\BeforeScenarioScope;
use Behat\Behat\Tester\Result\DefinedStepResult;

final class FaultlineDependencyContext implements Context
{
    private ?array $context = null;
    private array $files = [];
    private array $gaps = [];
    private bool $ownsCoverage = false;

    /** @BeforeScenario */
    public function faultlineStart(BeforeScenarioScope $scope): void
    {
        $path = getenv('FAULTLINE_DEPENDENCY_CONTEXT');
        if (!$path) return;
        $this->context = json_decode(file_get_contents($path), true, 512, JSON_THROW_ON_ERROR);
        $this->files = [];
        $this->gaps = ['External browser/server execution is not covered by this PHP process.'];
        if (getenv('FAULTLINE_DEPENDENCY_COVERAGE') === '1') {
            if (function_exists('xdebug_start_code_coverage') && !xdebug_code_coverage_started()) {
                xdebug_start_code_coverage();
                $this->ownsCoverage = true;
            } else {
                $this->gaps[] = 'Xdebug coverage unavailable or already owned by another collector.';
            }
        }
    }

    private function relative(string $path): ?string
    {
        $root = rtrim(str_replace('\\', '/', $this->context['root']), '/') . '/';
        $path = str_replace('\\', '/', realpath($path) ?: $path);
        if (!str_starts_with($path, $root)) return null;
        $path = substr($path, strlen($root));
        return array_key_exists($path, $this->context['tree']) ? $path : null;
    }

    /** @AfterStep */
    public function faultlineStep(AfterStepScope $scope): void
    {
        if ($this->context === null) return;
        $result = $scope->getTestResult();
        if ($result instanceof DefinedStepResult && $result->getStepDefinition() !== null) {
            $file = $result->getStepDefinition()->getReflection()->getFileName();
            $path = $file ? $this->relative($file) : null;
            if ($path !== null) $this->files[$path] = true;
            else $this->gaps[] = 'Step definition is outside tracked repository source.';
        } else {
            $this->gaps[] = 'Step definition was not resolved.';
        }
    }

    /** @AfterScenario */
    public function faultlineFinish(AfterScenarioScope $scope): void
    {
        if ($this->context === null) return;
        if ($this->ownsCoverage) {
            $coverage = xdebug_get_code_coverage();
            xdebug_stop_code_coverage();
            $this->ownsCoverage = false;
            foreach ($coverage as $file => $lines) {
                if (!array_filter($lines, fn($count) => is_int($count) && $count > 0)) continue;
                $path = $this->relative($file);
                if ($path !== null) $this->files[$path] = true;
            }
        }
        $test = $this->relative($scope->getFeature()->getFile());
        if ($test === null) throw new RuntimeException('Faultline feature is outside its source snapshot');
        $record = ['version' => 1, 'context' => $this->context['integrity'], 'producer' => 'behat',
                   'test_source' => $test, 'test_identity' => $test . ':' . $scope->getScenario()->getLine(),
                   'status' => $scope->getTestResult()->isPassed() ? 'passed' : 'failed',
                   'files' => array_keys($this->files), 'resources' => [], 'gaps' => array_values(array_unique($this->gaps))];
        $directory = getenv('FAULTLINE_DEPENDENCY_OUTPUT');
        if (!$directory) throw new RuntimeException('Set FAULTLINE_DEPENDENCY_OUTPUT for runtime evidence');
        if (!is_dir($directory) && !mkdir($directory, 0700, true) && !is_dir($directory)) throw new RuntimeException('Cannot create dependency evidence directory');
        $file = $directory . '/behat-' . bin2hex(random_bytes(12)) . '.json';
        if (file_put_contents($file, json_encode($record, JSON_THROW_ON_ERROR)) === false) throw new RuntimeException('Cannot persist dependency evidence');
    }
}
