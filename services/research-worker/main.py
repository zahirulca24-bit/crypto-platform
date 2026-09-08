import sys
import time

def main():
    print("[research-worker] Service initialized. Running in placeholder mode.", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[research-worker] Shutting down gracefully.", flush=True)

if __name__ == "__main__":
    main()
