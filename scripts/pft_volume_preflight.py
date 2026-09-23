"""Read-only M0 identity check before any proposed Production volume reuse."""
import json
import subprocess

VOLUME = "personal-finance-tracker_pgdata_production_backfill"
OLD_CONTAINER = "personal-finance-tracker-db-production-backfill-1"


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True)


def main():
    volume = json.loads(docker("volume", "inspect", VOLUME))[0]
    if volume["Name"] != VOLUME or volume["Driver"] != "local":
        raise RuntimeError("M0 Production volume identity mismatch")
    mounted = []
    ids = docker("ps", "-aq").split()
    if ids:
        for container in json.loads(docker("inspect", *ids)):
            if any(mount.get("Name") == VOLUME for mount in container.get("Mounts", [])):
                matching = [mount for mount in container["Mounts"] if mount.get("Name") == VOLUME]
                if any(mount.get("Destination") != "/var/lib/postgresql/data" for mount in matching):
                    raise RuntimeError("M0 volume mount destination mismatch")
                mounted.append({"name": container["Name"].lstrip("/"),
                                "running": container["State"]["Running"]})
    if not mounted:
        raise RuntimeError("M0 container mount evidence is missing; renewed identity review is required")
    if any(row["running"] for row in mounted):
        raise RuntimeError("Production volume is mounted by a running container; cutover must stop the old writer first")
    if mounted and any(row["name"] != OLD_CONTAINER for row in mounted):
        raise RuntimeError("Production volume has an unexpected stopped container mount")
    print("Verified exact M0 volume; no running container mounts it. This does not authorize cutover.")


if __name__ == "__main__":
    main()
