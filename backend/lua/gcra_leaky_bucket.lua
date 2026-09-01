-- GCRA Leaky Bucket Lua Script
local key = KEYS[1]
local burst = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local period = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local now = tonumber(ARGV[5]) -- in seconds

local emission_interval = period / rate
local increment = emission_interval * cost
local burst_offset = emission_interval * burst

local tat = redis.call("GET", key)
if not tat then
    tat = now
else
    tat = tonumber(tat)
end

tat = math.max(tat, now)

local new_tat = tat + increment
local allow_at = new_tat - burst_offset

if allow_at <= now then
    -- allowed
    redis.call("SET", key, new_tat)
    local ttl = math.ceil(new_tat - now)
    redis.call("EXPIRE", key, ttl)
    return {1, 0} -- 1 means allowed, 0 retry after
else
    -- rejected
    local retry_after = math.ceil(allow_at - now)
    return {0, retry_after}
end
