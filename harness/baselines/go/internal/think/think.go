// Package think adds the optional pause between requests that the runner's --think-time asks for.
//
// WH_THINK_TIME is unset (no pause), "3" (3 seconds) or "2-6" (a random time between 2 and 6
// seconds), the same format the Python, Node and curl baselines read.
package think

import (
	"fmt"
	"math/rand/v2"
	"os"
	"strconv"
	"strings"
	"time"
)

// Env is the variable the runner sets.
const Env = "WH_THINK_TIME"

// Range parses a WH_THINK_TIME value into its lower and upper bound in seconds.
func Range(value string) (lo, hi float64, err error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0, 0, nil
	}
	low, high, isRange := strings.Cut(value, "-")
	lo, errLo := strconv.ParseFloat(low, 64)
	hi = lo
	var errHi error
	if isRange {
		hi, errHi = strconv.ParseFloat(high, 64)
	}
	if errLo != nil || errHi != nil || lo < 0 || hi < lo {
		return 0, 0, fmt.Errorf("invalid %s=%q: use seconds (3) or a range (2-6)", Env, value)
	}
	return lo, hi, nil
}

// Check exits with status 2 if WH_THINK_TIME is malformed, so a run fails before its first request.
func Check() {
	if _, _, err := Range(os.Getenv(Env)); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

// Pause sleeps for a random time within WH_THINK_TIME, or not at all when it is unset.
func Pause() {
	lo, hi, err := Range(os.Getenv(Env))
	if err != nil || hi <= 0 {
		return
	}
	time.Sleep(time.Duration((lo + rand.Float64()*(hi-lo)) * float64(time.Second)))
}
