import { NativeModule, requireOptionalNativeModule } from 'expo';

import { PcmRecorderModuleEvents } from './PcmRecorder.types';

declare class PcmRecorderModule extends NativeModule<PcmRecorderModuleEvents> {
  start(): Promise<boolean>;
  stop(): Promise<boolean>;
}

export default requireOptionalNativeModule<PcmRecorderModule>('PcmRecorder');
