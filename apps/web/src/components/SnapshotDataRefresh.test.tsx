import { cleanup, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { afterEach, expect, it } from 'vitest';
import { SnapshotDataRefresh } from './App';

let requests = 0;

function ActiveTopicsQuery() {
  useQuery({ queryKey: ['topics', 'test'], queryFn: async () => ++requests });
  return null;
}

afterEach(() => {
  cleanup();
  requests = 0;
});

it('refresca las consultas activas cuando cambia el snapshot y no cuando se conserva', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const tree = (snapshotId: string) => (
    <QueryClientProvider client={client}>
      <SnapshotDataRefresh snapshotId={snapshotId} />
      <ActiveTopicsQuery />
    </QueryClientProvider>
  );
  const view = render(tree('snapshot-a'));
  await waitFor(() => expect(requests).toBe(1));

  view.rerender(tree('snapshot-a'));
  expect(requests).toBe(1);
  view.rerender(tree('snapshot-b'));
  await waitFor(() => expect(requests).toBe(2));
  client.clear();
});
