import type { TestType } from '@playwright/test';

export interface FaultlineDependencies {
  file(path: string): void;
  request(method: string, absoluteUrl: string): void;
  /** Observe request attempts without changing the original context or cookies. */
  requestContext<T extends object>(client: T, baseURL?: string): T;
}

export interface FaultlineFixtures {
  faultlineDependencies: FaultlineDependencies;
}

export function withFaultline<T extends object, W extends object>(
  base: TestType<T, W>,
): TestType<T & FaultlineFixtures, W>;
