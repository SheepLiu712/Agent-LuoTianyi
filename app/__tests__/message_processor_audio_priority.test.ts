const mockAppState = { currentState: 'active' };
const mockSoundInstances: Array<Record<string, jest.Mock>> = [];
const mockSoundConstructor = jest.fn(() => {
  const sound = {
    loadAsync: jest.fn().mockResolvedValue(undefined),
    playAsync: jest.fn().mockResolvedValue(undefined),
    stopAsync: jest.fn().mockResolvedValue(undefined),
    unloadAsync: jest.fn().mockResolvedValue(undefined),
    setOnPlaybackStatusUpdate: jest.fn(),
  };
  mockSoundInstances.push(sound);
  return sound;
});

jest.mock('react-native', () => ({ AppState: mockAppState }));
jest.mock('expo-av', () => ({ Audio: { Sound: mockSoundConstructor } }));
jest.mock('expo-file-system/legacy', () => ({
  documentDirectory: 'file://documents/',
  EncodingType: { Base64: 'base64' },
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true }),
  readAsStringAsync: jest.fn().mockResolvedValue(''),
}));

import * as FileSystem from 'expo-file-system/legacy';
import { AgentBinder } from '../utils/binder';
import { MessageProcessor } from '../utils/message_processor';
import { NetworkClient } from '../utils/network_client';


function fakeBinder() {
  return {
    emitAgentMessage: jest.fn(),
    emitErrorText: jest.fn(),
    emitMessageStatus: jest.fn(),
    emitLocalTtsState: jest.fn(),
  } as unknown as jest.Mocked<AgentBinder>;
}

async function drainIncoming(processor: MessageProcessor) {
  await (processor as unknown as { incomingMessageChain: Promise<void> }).incomingMessageChain;
}

describe('MessageProcessor online audio priority', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockSoundInstances.length = 0;
    mockAppState.currentState = 'active';
    (FileSystem.getInfoAsync as jest.Mock).mockResolvedValue({ exists: true });
  });

  it('cancels a replay start when server audio arrives during file lookup', async () => {
    let resolveFileInfo: ((value: { exists: boolean }) => void) | undefined;
    (FileSystem.getInfoAsync as jest.Mock).mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveFileInfo = resolve;
      }),
    );
    const processor = new MessageProcessor(
      {} as NetworkClient,
      fakeBinder(),
      jest.fn(),
    );
    processor.setLocalAudioPath('saved-message', 'file://saved.wav');

    const replayStarted = processor.playLocalTtsByUuid('saved-message');
    processor.onAgentMessage({
      uuid: 'online-message',
      audio: 'c2VydmVy',
      is_final_package: false,
    });
    resolveFileInfo?.({ exists: true });

    expect(await replayStarted).toBe(false);
    await drainIncoming(processor);
    expect(mockSoundConstructor).not.toHaveBeenCalled();
  });

  it('stops an active replay before feeding server audio and blocks further replay', async () => {
    const events: string[] = [];
    mockSoundConstructor.mockImplementationOnce(() => {
      const sound = {
        loadAsync: jest.fn(async () => { events.push('local-loaded'); }),
        playAsync: jest.fn(async () => { events.push('local-playing'); }),
        stopAsync: jest.fn(async () => { events.push('local-stopped'); }),
        unloadAsync: jest.fn(async () => { events.push('local-unloaded'); }),
        setOnPlaybackStatusUpdate: jest.fn(),
      };
      mockSoundInstances.push(sound);
      return sound;
    });
    const binder = fakeBinder();
    const feedServerAudioChunk = jest.fn(() => { events.push('server-fed'); });
    const processor = new MessageProcessor(
      {} as NetworkClient,
      binder,
      feedServerAudioChunk,
    );
    processor.setLocalAudioPath('saved-message', 'file://saved.wav');

    expect(await processor.playLocalTtsByUuid('saved-message')).toBe(true);
    processor.onAgentMessage({
      uuid: 'online-message',
      audio: 'c2VydmVy',
      is_final_package: false,
    });
    await drainIncoming(processor);

    expect(events).toEqual([
      'local-loaded',
      'local-playing',
      'local-stopped',
      'local-unloaded',
      'server-fed',
    ]);
    expect(binder.emitLocalTtsState).toHaveBeenCalledWith('stopped', 'saved-message');
    expect(await processor.playLocalTtsByUuid('saved-message')).toBe(false);
    expect(mockSoundConstructor).toHaveBeenCalledTimes(1);
  });
});
