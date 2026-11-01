/** Keep a paged view's state with its newest request, including errors and busy state. */
export class LatestRequest {
  private generation = 0;

  invalidate(): void {
    this.generation += 1;
  }

  async run<T>(load: () => Promise<T>, handlers: {
    start: () => void;
    success: (value: T) => void;
    error: (error: unknown) => void;
    finish: () => void;
  }): Promise<void> {
    const mine = ++this.generation;
    handlers.start();
    try {
      const value = await load();
      if (mine === this.generation) handlers.success(value);
    } catch (error) {
      if (mine === this.generation) handlers.error(error);
    } finally {
      if (mine === this.generation) handlers.finish();
    }
  }
}
