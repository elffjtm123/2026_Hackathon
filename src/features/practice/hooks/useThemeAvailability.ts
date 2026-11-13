import { useCallback, useEffect, useState } from 'react';
import { readModelAvailability, type ModelAvailability, type ModelTheme } from '../../model-themes/modelThemes';

// File readiness of an experiment STT model. The service theme never queries the experiments API.
export function useThemeAvailability(theme: ModelTheme) {
  const [availability, setAvailability] = useState<ModelAvailability | null>(null);
  const [availabilityError, setAvailabilityError] = useState<string | null>(null);
  const refreshAvailability = useCallback(async (isDisposed: () => boolean = () => false) => {
    if (!theme.experiment) return;
    try {
      const body = await readModelAvailability();
      if (!isDisposed()) { setAvailability(body.models.find(model => model.id === theme.id) ?? null); setAvailabilityError(null); }
    } catch (cause) { if (!isDisposed()) setAvailabilityError(cause instanceof Error ? cause.message : '모델 상태 확인 실패'); }
  }, [theme.id, theme.experiment]);
  useEffect(() => { let disposed = false; void refreshAvailability(() => disposed); return () => { disposed = true; }; }, [refreshAvailability]);
  return { availability, availabilityError, refreshAvailability };
}
