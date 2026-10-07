// Persistent byte-backed filesystem double. New managers see the same disk contents.
export function createVoiceFileSystem() {
  const files = new Map<string, { data: Buffer; modified: number }>();
  const put = (uri: string, data: Buffer | string) => files.set(uri, {
    data: Buffer.isBuffer(data) ? data : Buffer.from(data), modified: Date.now() / 1000,
  });
  return {
    files, put, documentDirectory: 'file://documents/', EncodingType: { Base64: 'base64' },
    makeDirectoryAsync: jest.fn(async () => undefined),
    readDirectoryAsync: jest.fn(async (dir: string) => [...files.keys()]
      .filter((uri) => uri.startsWith(`${dir}/`)).map((uri) => uri.slice(dir.length + 1))),
    getInfoAsync: jest.fn(async (uri: string) => {
      const file = files.get(uri);
      return file ? { exists: true, isDirectory: false, size: file.data.length, modificationTime: file.modified } : { exists: false };
    }),
    readAsStringAsync: jest.fn(async (uri: string, options?: { encoding: string }) => {
      const file = files.get(uri);
      if (!file) throw new Error(`missing file: ${uri}`);
      return file.data.toString(options?.encoding === 'base64' ? 'base64' : 'utf8');
    }),
    writeAsStringAsync: jest.fn(async (uri: string, data: string, options?: { encoding: string }) => {
      put(uri, Buffer.from(data, options?.encoding === 'base64' ? 'base64' : 'utf8'));
    }),
    copyAsync: jest.fn(async ({ from, to }: { from: string; to: string }) => {
      const file = files.get(from);
      if (!file) throw new Error(`missing source: ${from}`);
      put(to, file.data);
    }),
    moveAsync: jest.fn(async ({ from, to }: { from: string; to: string }) => {
      const file = files.get(from);
      if (!file) throw new Error(`missing source: ${from}`);
      files.set(to, file); files.delete(from);
    }),
    deleteAsync: jest.fn(async (uri: string) => {
      for (const key of files.keys()) if (key === uri || key.startsWith(`${uri}/`)) files.delete(key);
    }),
  };
}
export type VoiceFileSystem = ReturnType<typeof createVoiceFileSystem>;
