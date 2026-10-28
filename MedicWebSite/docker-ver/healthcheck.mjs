try {
  await Promise.all([3000, 3001].map(async (port) => {
    const response = await fetch(`http://127.0.0.1:${port}/api/v1/health`, {
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok || (await response.json()).status !== "ok") {
      throw new Error(`Unhealthy website entry: ${port}`);
    }
  }));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
