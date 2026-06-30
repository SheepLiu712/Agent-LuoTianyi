import { useCallback, useEffect, useRef, useState } from 'react';
import { AffectionInfo, getAffectionInfo } from '../utils/getAffection';

export function useAffection(username: string, messageToken: string) {
  const [affection, setAffection] = useState<AffectionInfo | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchAffection = useCallback(async () => {
    if (!username || !messageToken) {
      return;
    }
    const info = await getAffectionInfo(username, messageToken);
    if (info) {
      setAffection(info);
    }
  }, [username, messageToken]);

  useEffect(() => {
    fetchAffection();
    intervalRef.current = setInterval(fetchAffection, 60000);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchAffection]);

  return { affection, refreshAffection: fetchAffection };
}
