import { NativeCallRingtone } from '../utils/call_session/ringtone';

const native = { startRingtone: jest.fn(), stopRingtone: jest.fn() };
jest.mock('expo-modules-core', () => ({ requireOptionalNativeModule: () => native }));
jest.mock('expo-av', () => { throw new Error('呼叫铃声不得创建第二个音频焦点所有者'); });

describe('NativeCallRingtone', () => {
  beforeEach(() => jest.clearAllMocks());

  it('starts one native ringtone and stops it when dialing ends', () => {
    const ringtone = new NativeCallRingtone();
    ringtone.playLoop();
    ringtone.playLoop();
    expect(native.startRingtone).toHaveBeenCalledTimes(1);
    ringtone.stop();
    ringtone.stop();
    expect(native.stopRingtone).toHaveBeenCalledTimes(1);
    ringtone.playLoop();
    expect(native.startRingtone).toHaveBeenCalledTimes(2);
    ringtone.stop();
  });

  it('surfaces native playback failure without claiming the ringtone is playing', () => {
    native.startRingtone.mockImplementationOnce(() => { throw new Error('ringtone_start_failed'); });
    const ringtone = new NativeCallRingtone();
    expect(() => ringtone.playLoop()).toThrow('ringtone_start_failed');
    ringtone.stop();
    expect(native.stopRingtone).not.toHaveBeenCalled();
  });
});
