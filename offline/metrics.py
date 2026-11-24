"""Başvuru §2.10: ortak adımlarda kayıt başarısı ve yanlış alarm dönemleri."""

import numpy as np


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def score(labels, decisions, continues, step_seconds):
    tp = int(np.count_nonzero(labels & decisions))
    fp = int(np.count_nonzero(~labels & decisions))
    fn = int(np.count_nonzero(labels & ~decisions))
    tn = len(labels) - tp - fp - fn
    previous_alarm = np.r_[False, decisions[:-1]] if len(decisions) else decisions
    alarm_start = decisions & ~(continues & previous_alarm)
    false_alarms = int(np.count_nonzero(alarm_start & ~labels))
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=ratio(tp, tp + fp),
                recall=ratio(tp, tp + fn), f1=ratio(2 * tp, 2 * tp + fp + fn),
                alarm_periods=int(np.count_nonzero(alarm_start)), false_alarm_periods=false_alarms,
                false_alarms_per_24_sensor_hours=ratio(false_alarms * 86400, len(labels) * step_seconds))


def ranking(metrics, preference):
    def defined(value):
        return value if value is not None else -float('inf')

    alarm_rate = metrics['false_alarms_per_24_sensor_hours']
    return (defined(metrics['f1']), defined(metrics['recall']),
            defined(-alarm_rate if alarm_rate is not None else None), *preference)
