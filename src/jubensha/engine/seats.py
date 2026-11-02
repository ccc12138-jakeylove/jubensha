from jubensha.schema.state import GameState, SeatState


def current_seat(state: GameState, seat_id: str) -> SeatState:
    try:
        return state.seats[seat_id]
    except KeyError as exc:
        raise PermissionError("seat does not belong to this game") from exc
